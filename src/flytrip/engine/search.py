"""Search orchestration: Kiwi explores, Google confirms, results stream out as events."""

import asyncio
import logging
import math
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, ValidationError

from flytrip.core.calendar import CalendarDay, build_calendar
from flytrip.core.candidates import DatePair, select_google_candidates
from flytrip.core.models import Itinerary
from flytrip.core.query import MENDOZA_TZ, SearchQuery
from flytrip.core.ranking import (
    apply_transfers,
    best_balance,
    best_per_origin,
    keep_true_origin,
    mark_separate_tickets,
    merge_duplicates,
    sort_by_total,
)
from flytrip.engine.cache import SearchCache
from flytrip.engine.settings import Settings
from flytrip.sources.base import (
    BLOCK_PAUSE_MINUTES,
    PauseRegistry,
    Source,
    SourceRequest,
    SourceResult,
    run_safely,
)
from flytrip.sources.google_flights import GOOGLE_FETCH_BUDGET
from flytrip.sources.kiwi import KIWI_MAX_WINDOW_DAYS
from flytrip.sources.skiplagged import (
    SKIPLAGGED_CALL_BUDGET,
    CalendarResult,
)

log = logging.getLogger("flytrip.search")

NO_DATES_DETAIL = "Sin fechas para confirmar"
GOOGLE_SILENT_BLOCK = "Google no devolvió resultados para ninguna fecha (posible bloqueo)"
SKIPLAGGED_SILENT_BLOCK = "Skiplagged no devolvió resultados para ninguna fecha (posible bloqueo)"
CALENDAR_UNAVAILABLE = "Calendario no disponible: {reason}"
# One calendar call returns about 48 days: anchor - 30 to anchor + 17 (docs/sources/skiplagged.md).
CALENDAR_FIRST_ANCHOR_DAYS = 30
CALENDAR_NEXT_ANCHOR_DAYS = 31
CALENDAR_SPAN_DAYS = 48
CALENDAR_MAX_CALLS_PER_ORIGIN = 3
SKIPLAGGED_MAX_CALLS_PER_SEARCH = 12  # calendar plus confirmation
SKIPLAGGED_SOFT_DEADLINE_S = 28
CALENDAR_CUT_GRACE_S = 0.5
CALENDAR_INCOMPLETE = "Calendario incompleto: {failures}"
CalendarEntry = tuple[str, date, Decimal]
CalendarTask = asyncio.Task[tuple[tuple[CalendarEntry, ...], str]]

SourceState = Literal[
    "pending", "running", "ok", "partial", "paused", "error", "timeout", "skipped"
]


class CalendarSource(Source, Protocol):
    """A source that confirms exact dates and also prices a month calendar (Skiplagged)."""

    async def calendar(
        self, origin: str, destination: str, anchor: date, return_date: date | None
    ) -> CalendarResult: ...


class SourceStatus(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    state: SourceState
    detail: str = ""
    latency_ms: int | None = None
    count: int = 0


class SearchSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    query: SearchQuery
    itineraries: tuple[Itinerary, ...]
    best_per_origin: dict[str, Itinerary | None]
    best_balance: Itinerary | None
    statuses: dict[str, SourceStatus]
    # Origin -> why it could not be queried, when every call for that origin failed.
    failed_origins: dict[str, str] = {}
    # Month mode: the cheapest day per date (transfers included) and why it may be missing.
    calendar: tuple[CalendarDay, ...] = ()
    calendar_note: str = ""
    # Month mode, interim snapshots only: the calendar is still being fetched.
    calendar_pending: bool = False
    # Raw (origin, day, price) so a cached snapshot can rebuild `calendar` with today's transfers.
    calendar_entries: tuple[CalendarEntry, ...] = ()
    completed_at: datetime
    from_cache: bool = False
    cache_age_minutes: int | None = None


@dataclass(frozen=True)
class StatusEvent:
    status: SourceStatus


@dataclass(frozen=True)
class SnapshotEvent:
    snapshot: SearchSnapshot
    final: bool


def _kiwi_requests(query: SearchQuery) -> list[SourceRequest]:
    """Protected mode for every origin, plus the "all" mode when separate tickets are allowed."""
    modes = (False, True) if query.allow_separate_tickets else (False,)
    return [
        SourceRequest(
            origin=origin,
            destination=query.destination,
            depart_from=query.depart_from,
            depart_to=query.depart_to,
            nights_min=query.nights_min,
            nights_max=query.nights_max,
            adults=query.adults,
            allow_separate_tickets=mode,
        )
        for origin in query.origins
        for mode in modes
    ]


def _google_request(pair: DatePair, query: SearchQuery) -> SourceRequest:
    nights = None if pair.return_date is None else (pair.return_date - pair.depart).days
    return SourceRequest(
        origin=pair.origin,
        destination=pair.destination_airport,
        depart_from=pair.depart,
        depart_to=pair.depart,
        nights_min=nights,
        nights_max=nights,
        adults=query.adults,
        allow_separate_tickets=query.allow_separate_tickets,
    )


def _combine_modes(
    everything: SourceResult | None, protected: SourceResult | None
) -> list[Itinerary]:
    """One origin's Kiwi itineraries, flagged by comparing the "all" and protected modes."""
    safe = (
        []
        if protected is None
        else [it.model_copy(update={"separate_tickets": False}) for it in protected.itineraries]
    )
    if everything is None or everything.status != "ok":
        return safe
    if protected is None or protected.status != "ok":
        return list(everything.itineraries)  # without the protected mode the flag stays unknown
    marked = mark_separate_tickets(everything.itineraries, protected.itineraries)
    seen = {it.id for it in marked}
    return marked + [it for it in safe if it.id not in seen]


def planned_calendar_calls(query: SearchQuery) -> int:
    """The most calendar calls a search makes: per origin, enough 48-day calls for the window."""
    span = (query.depart_to - query.depart_from).days + 1
    per_origin = min(CALENDAR_MAX_CALLS_PER_ORIGIN, math.ceil(span / CALENDAR_SPAN_DAYS))
    return per_origin * len(query.origins)


@dataclass
class _CalendarProgress:
    """What the calendar phase has so far; survives a cancellation of the phase."""

    entries: list[CalendarEntry] = field(default_factory=list)
    failures: dict[str, str] = field(default_factory=dict)


def _pause_detail(until: datetime, reason: str) -> str:
    return f"En pausa hasta las {until.astimezone(MENDOZA_TZ):%H:%M}: {reason}"


class SearchEngine:
    def __init__(
        self,
        *,
        kiwi: Source,
        google: Source,
        settings_provider: Callable[[], Settings],
        cache: SearchCache,
        pauses: PauseRegistry,
        clock: Callable[[], datetime],
        kiwi_timeout_s: float = 20,
        google_timeout_s: float = 40,
        skiplagged: CalendarSource | None = None,
        hard_timeout_s: float = 60,
        skiplagged_soft_deadline_s: float = SKIPLAGGED_SOFT_DEADLINE_S,
    ) -> None:
        self.kiwi = kiwi
        self.google = google
        self.skiplagged = skiplagged
        self._settings_provider = settings_provider
        self._cache = cache
        self._pauses = pauses
        self._clock = clock
        self._kiwi_timeout_s = kiwi_timeout_s
        self._google_timeout_s = google_timeout_s
        self._hard_timeout_s = hard_timeout_s
        self._skiplagged_soft_s = skiplagged_soft_deadline_s
        self._cut_detail = f"La búsqueda se cortó a los {hard_timeout_s:g} s"

    async def aclose(self) -> None:
        for source in (self.kiwi, self.google, self.skiplagged):
            close = getattr(source, "aclose", None)
            if close is not None:
                await close()

    @property
    def settings(self) -> Settings:
        """The settings as they are right now (saved changes apply without a restart)."""
        return self._settings_provider()

    @property
    def max_window_days(self) -> int:
        return min(365, 4 * KIWI_MAX_WINDOW_DAYS)

    async def run(
        self, query: SearchQuery, *, use_cache: bool = True
    ) -> AsyncIterator[StatusEvent | SnapshotEvent]:
        key = query.cache_key()
        settings = self.settings  # read once per run: one search never mixes two settings
        cached = self._from_cache(key, query, settings) if use_cache else None
        if cached is not None:
            yield SnapshotEvent(snapshot=cached, final=True)
            return
        # An absolute deadline checked at each await: a timeout scope must never span a yield.
        deadline = asyncio.get_running_loop().time() + self._hard_timeout_s
        statuses = {
            self.kiwi.name: SourceStatus(source=self.kiwi.name, state="running"),
            self.google.name: SourceStatus(source=self.google.name, state="pending"),
        }
        if self.skiplagged is not None:
            statuses[self.skiplagged.name] = SourceStatus(
                source=self.skiplagged.name, state="pending"
            )
        for status in statuses.values():
            yield StatusEvent(status=status)

        # The calendar runs next to Kiwi; its failure only ever sets `calendar_note`.
        calendar_task = (
            asyncio.create_task(self._calendar_phase(query, deadline)) if query.calendar else None
        )
        try:
            async for event in self._run_phases(
                query, settings, key, deadline, statuses, calendar_task
            ):
                yield event
        finally:
            if calendar_task is not None and not calendar_task.done():
                calendar_task.cancel()
                await asyncio.gather(calendar_task, return_exceptions=True)

    async def _run_phases(
        self,
        query: SearchQuery,
        settings: Settings,
        key: str,
        deadline: float,
        statuses: dict[str, SourceStatus],
        calendar_task: CalendarTask | None,
    ) -> AsyncIterator[StatusEvent | SnapshotEvent]:
        found, kiwi_status, cut, failed_origins = await self._explore(query, deadline)
        yield self._finish(kiwi_status, statuses, key)
        confirmed: list[Itinerary] = []
        if cut:
            for source in self._confirmers():
                cut_status = SourceStatus(
                    source=source.name, state="timeout", detail=self._cut_detail
                )
                yield self._finish(cut_status, statuses, key)
        else:
            early = self._calendar_result(calendar_task) if calendar_task is not None else ((), "")
            waiting = calendar_task is not None and not calendar_task.done()
            yield SnapshotEvent(
                snapshot=self._snapshot(
                    query, found, statuses, settings, failed_origins, *early, pending=waiting
                ),
                final=False,
            )
            active: list[tuple[Source, list[DatePair], float, str]] = []
            for source, pairs, timeout_s, silent in self._plans(query, found):
                hold = self._hold(source, pairs)
                if hold is not None:
                    yield self._finish(hold, statuses, key)
                    continue
                running = SourceStatus(source=source.name, state="running")
                statuses[running.source] = running
                yield StatusEvent(status=running)
                active.append((source, pairs, timeout_s, silent))
            tasks = [
                asyncio.create_task(
                    self._confirm(
                        source,
                        query,
                        pairs,
                        timeout_s,
                        deadline,
                        silent,
                        self._skiplagged_soft_s if source is self.skiplagged else None,
                    )
                )
                for source, pairs, timeout_s, silent in active
            ]
            try:
                # Each source reports as soon as it finishes, not when the slowest does.
                for finished in asyncio.as_completed(tasks):
                    items, status = await finished
                    confirmed.extend(items)
                    yield self._finish(status, statuses, key)
            finally:
                pending = [t for t in tasks if not t.done()]
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

        entries, note = (
            await self._calendar_wait(calendar_task, deadline) if calendar_task else ((), "")
        )
        merged = merge_duplicates([*found, *confirmed])
        if not query.allow_separate_tickets:
            merged = [it for it in merged if it.separate_tickets is not True]
        final = self._snapshot(query, merged, statuses, settings, failed_origins, entries, note)
        calendar_failed = query.calendar and bool(final.calendar_note)
        # A snapshot whose calendar failed is not cached: the next search should retry it.
        if not calendar_failed and any(s.state == "ok" for s in statuses.values()):
            self._cache.put(key, final.model_dump_json())
        yield SnapshotEvent(snapshot=final, final=True)

    def _confirmers(self) -> list[Source]:
        return [self.google] + ([self.skiplagged] if self.skiplagged is not None else [])

    def _plans(
        self, query: SearchQuery, found: Sequence[Itinerary]
    ) -> list[tuple[Source, list[DatePair], float, str]]:
        """Each confirming source with its candidate pairs, timeout and silent-block message."""
        plans: list[tuple[Source, list[DatePair], float, str]] = [
            (
                self.google,
                select_google_candidates(found, query, GOOGLE_FETCH_BUDGET),
                self._google_timeout_s,
                GOOGLE_SILENT_BLOCK,
            )
        ]
        if self.skiplagged is not None:
            # One search call per pair, sharing the per-search cap with the calendar calls.
            planned = planned_calendar_calls(query) if query.calendar else 0
            pairs = max(0, min(SKIPLAGGED_CALL_BUDGET, SKIPLAGGED_MAX_CALLS_PER_SEARCH - planned))
            # The selector counts a round trip as 2 fetches.
            budget = pairs * (1 if query.trip_type == "oneway" else 2)
            plans.append(
                (
                    self.skiplagged,
                    select_google_candidates(found, query, budget),
                    self._hard_timeout_s,  # the source times each HTTP call itself
                    SKIPLAGGED_SILENT_BLOCK,
                )
            )
        return plans

    async def _explore(
        self, query: SearchQuery, deadline: float
    ) -> tuple[list[Itinerary], SourceStatus, bool, dict[str, str]]:
        started = time.monotonic()
        requests = _kiwi_requests(query)
        outcomes, cut = await self._call_all(self.kiwi, requests, self._kiwi_timeout_s, deadline)
        by_mode = {
            (request.origin, request.allow_separate_tickets): outcome
            for request, outcome in zip(requests, outcomes, strict=True)
        }
        found = [
            it
            for origin in query.origins
            for it in _combine_modes(by_mode.get((origin, True)), by_mode.get((origin, False)))
        ]
        status = self._summary(self.kiwi.name, requests, outcomes, cut, len(found), started)
        return found, status, cut, self._failed_origins(requests, outcomes)

    async def _confirm(
        self,
        source: Source,
        query: SearchQuery,
        pairs: Sequence[DatePair],
        timeout_s: float,
        deadline: float,
        silent_block: str,
        soft_s: float | None = None,
    ) -> tuple[list[Itinerary], SourceStatus]:
        # All calls start together, so a per-call timeout bounds the whole phase; each
        # source's own semaphore keeps them at their concurrency.
        started = time.monotonic()
        requests = [_google_request(pair, query) for pair in pairs]
        limit = deadline
        if soft_s is not None:
            limit = min(deadline, asyncio.get_running_loop().time() + soft_s)
        outcomes, cut = await self._call_all(source, requests, timeout_s, limit)
        confirmed = [
            it for outcome in outcomes if outcome is not None for it in outcome.itineraries
        ]
        status = self._summary(source.name, requests, outcomes, cut, len(confirmed), started)
        if cut and limit < deadline:
            # The soft deadline, not the hard cut: keep what finished and say what was lost.
            finished = any(o is not None and o.status == "ok" for o in outcomes)
            status = status.model_copy(
                update={
                    "state": "partial" if finished else "timeout",
                    "detail": f"se cortó a los {soft_s:g} s",
                }
            )
        # Only an API that itself returned nothing looks like a block, not one whose answers
        # were all thrown away.
        silent = (
            requests
            and not confirmed
            and all(o is not None and o.status == "ok" and not o.raw_count for o in outcomes)
        )
        if silent:
            # These sources answer a block (captcha, consent page) with an empty page.
            self._pauses.pause(source.name, BLOCK_PAUSE_MINUTES, silent_block)
            status = status.model_copy(update={"state": "error", "detail": silent_block})
        return confirmed, status

    # -- calendar ------------------------------------------------------------------------

    async def _calendar_origin(
        self, skiplagged: CalendarSource, query: SearchQuery, origin: str, out: _CalendarProgress
    ) -> None:
        """One origin's calendar: sequential calls, each starting where the last one ended."""
        anchor = query.depart_from + timedelta(days=CALENDAR_FIRST_ANCHOR_DAYS)
        for _ in range(CALENDAR_MAX_CALLS_PER_ORIGIN):
            back = None if query.nights_min is None else anchor + timedelta(days=query.nights_min)
            try:
                result = await skiplagged.calendar(origin, query.destination, anchor, back)
            except TimeoutError:
                out.failures.setdefault(origin, "Skiplagged no respondió a tiempo")
                return
            except Exception as exc:
                out.failures.setdefault(origin, f"error inesperado ({type(exc).__name__})")
                return
            if result.status == "paused":
                self._pauses.pause(skiplagged.name, result.pause_minutes, result.detail)
            if result.status != "ok":
                out.failures.setdefault(origin, result.detail)
                return
            if not result.days:
                return
            out.entries.extend(
                (origin, day, price * query.adults)  # the calendar prices one person
                for day, price in result.days
                if query.depart_from <= day <= query.depart_to
            )
            last = max(day for day, _ in result.days)
            if last >= query.depart_to:
                return
            anchor = last + timedelta(days=CALENDAR_NEXT_ANCHOR_DAYS)

    async def _calendar_phase(
        self, query: SearchQuery, deadline: float
    ) -> tuple[tuple[CalendarEntry, ...], str]:
        """(entries, note). Failures become the note instead of raising."""
        skiplagged = self.skiplagged
        if skiplagged is None:
            return (), CALENDAR_UNAVAILABLE.format(reason="Skiplagged no está configurado")
        pause = self._pauses.active_pause(skiplagged.name)
        if pause is not None:
            return (), CALENDAR_UNAVAILABLE.format(reason=_pause_detail(*pause))
        progress = _CalendarProgress()
        tasks = {
            origin: asyncio.create_task(self._calendar_origin(skiplagged, query, origin, progress))
            for origin in query.origins
        }
        try:
            if tasks:
                await asyncio.wait(
                    tasks.values(), timeout=max(deadline - asyncio.get_running_loop().time(), 0)
                )
        finally:
            late = [t for t in tasks.values() if not t.done()]
            for task in late:
                task.cancel()
            await asyncio.gather(*late, return_exceptions=True)
        for origin, task in tasks.items():
            if task.cancelled():
                progress.failures.setdefault(origin, self._cut_detail)
        if not progress.entries:
            reason = next(iter(progress.failures.values()), "sin datos")
            return (), CALENDAR_UNAVAILABLE.format(reason=reason)
        if progress.failures:
            failures = "; ".join(f"falló {o} ({why})" for o, why in progress.failures.items())
            return tuple(progress.entries), CALENDAR_INCOMPLETE.format(failures=failures)
        return tuple(progress.entries), ""

    @staticmethod
    def _calendar_result(task: CalendarTask) -> tuple[tuple[CalendarEntry, ...], str]:
        """What the calendar has so far: empty while it is still running."""
        if not task.done():
            return (), ""
        if task.cancelled():
            return (), CALENDAR_UNAVAILABLE.format(reason="se interrumpió")
        if task.exception() is not None:
            return (), CALENDAR_UNAVAILABLE.format(reason="error inesperado")
        return task.result()

    async def _calendar_wait(
        self, task: CalendarTask, deadline: float
    ) -> tuple[tuple[CalendarEntry, ...], str]:
        # The phase cuts itself at the same deadline; the grace lets it hand over what it has.
        remaining = max(deadline - asyncio.get_running_loop().time(), 0)
        await asyncio.wait([task], timeout=remaining + CALENDAR_CUT_GRACE_S)
        if not task.done():
            return (), CALENDAR_UNAVAILABLE.format(reason=self._cut_detail)
        return self._calendar_result(task)

    async def _call_all(
        self, source: Source, requests: Sequence[SourceRequest], timeout_s: float, deadline: float
    ) -> tuple[list[SourceResult | None], bool]:
        """Call the source once per request, all at once. None marks a call cut by the deadline."""
        tasks = [
            asyncio.create_task(
                run_safely(
                    source, request, timeout_s=timeout_s, pauses=self._pauses, clock=self._clock
                )
            )
            for request in requests
        ]
        if not tasks:
            return [], False
        try:
            remaining = deadline - asyncio.get_running_loop().time()
            await asyncio.wait(tasks, timeout=max(remaining, 0))
        finally:
            late = [task for task in tasks if not task.done()]
            for task in late:
                task.cancel()
            await asyncio.gather(*late, return_exceptions=True)
        outcomes = [None if task.cancelled() else task.result() for task in tasks]
        checked = [
            None if outcome is None else self._keep_true_origin(request, outcome)
            for request, outcome in zip(requests, outcomes, strict=True)
        ]
        return checked, bool(late)

    @staticmethod
    def _keep_true_origin(request: SourceRequest, outcome: SourceResult) -> SourceResult:
        """Drop itineraries that do not leave from (and return to) the origin that was asked."""
        kept, dropped = keep_true_origin(outcome.itineraries, request.origin)
        if not dropped:
            return outcome
        raw = len(outcome.itineraries) if outcome.raw_count is None else outcome.raw_count
        return replace(
            outcome, itineraries=tuple(kept), raw_count=raw, dropped=outcome.dropped + dropped
        )

    def _failed_origins(
        self, requests: Sequence[SourceRequest], outcomes: Sequence[SourceResult | None]
    ) -> dict[str, str]:
        """Origins where no call succeeded, each with the reason of its first failed call."""
        reasons: dict[str, str] = {}
        succeeded: set[str] = set()
        for request, outcome in zip(requests, outcomes, strict=True):
            if outcome is not None and outcome.status == "ok":
                succeeded.add(request.origin)
            else:
                detail = self._cut_detail if outcome is None else outcome.detail
                reasons.setdefault(request.origin, detail)
        return {origin: why for origin, why in reasons.items() if origin not in succeeded}

    def _summary(
        self,
        name: str,
        requests: Sequence[SourceRequest],
        outcomes: Sequence[SourceResult | None],
        cut: bool,
        count: int,
        started: float,
    ) -> SourceStatus:
        """One status for all the calls to a source.

        A pause wins, then the cut, then the mix: all failed is the failure itself, some failed is
        "partial" (it lists what failed) and all fine is "ok".
        """
        results = [outcome for outcome in outcomes if outcome is not None]
        latency_ms = int((time.monotonic() - started) * 1000)

        def status(state: SourceState, detail: str = "") -> SourceStatus:
            return SourceStatus(
                source=name, state=state, detail=detail, latency_ms=latency_ms, count=count
            )

        dropped = sum(r.dropped for r in results)
        note = f"Se descartaron {dropped} resultados que no cumplían lo pedido" if dropped else ""
        paused = next((r for r in results if r.status == "paused"), None)
        failed = next((r for r in results if r.status != "ok"), None)
        if paused is not None:
            return status("paused", paused.detail)
        if cut:
            return status("timeout", self._cut_detail)
        if failed is None:
            return status("ok", note)
        if not any(r.status == "ok" for r in results):
            return status(failed.status, failed.detail)
        failures = dict.fromkeys(
            f"falló {request.origin}: {outcome.detail}"
            for request, outcome in zip(requests, outcomes, strict=True)
            if outcome is not None and outcome.status != "ok"
        )
        return status("partial", "; ".join([*failures, *([note] if note else [])]))

    def _hold(self, source: Source, pairs: Sequence[DatePair]) -> SourceStatus | None:
        """Why a confirming source is not called this time, or None when it should be."""
        pause = self._pauses.active_pause(source.name)
        if pause is not None:
            return SourceStatus(source=source.name, state="paused", detail=_pause_detail(*pause))
        if not pairs:
            return SourceStatus(source=source.name, state="skipped", detail=NO_DATES_DETAIL)
        return None

    def _finish(
        self, status: SourceStatus, statuses: dict[str, SourceStatus], key: str
    ) -> StatusEvent:
        statuses[status.source] = status
        log.info(
            "source_done",
            extra={
                "source": status.source,
                "state": status.state,
                "latency_ms": status.latency_ms,
                "count": status.count,
                "query_key": key,
            },
        )
        return StatusEvent(status=status)

    def _snapshot(
        self,
        query: SearchQuery,
        itineraries: Sequence[Itinerary],
        statuses: dict[str, SourceStatus],
        settings: Settings,
        failed_origins: dict[str, str] | None = None,
        calendar_entries: tuple[CalendarEntry, ...] = (),
        calendar_note: str = "",
        pending: bool = False,
    ) -> SearchSnapshot:
        ranked = sort_by_total(apply_transfers(itineraries, settings.transfers))
        return SearchSnapshot(
            query=query,
            itineraries=tuple(ranked),
            best_per_origin=best_per_origin(ranked, query.origins),
            best_balance=best_balance(ranked, settings.usd_per_hour),
            statuses=dict(statuses),
            failed_origins=failed_origins or {},
            calendar=tuple(build_calendar(calendar_entries, settings.transfers)),
            calendar_note=calendar_note,
            calendar_pending=pending,
            calendar_entries=calendar_entries,
            completed_at=self._clock(),
        )

    def _from_cache(
        self, key: str, query: SearchQuery, settings: Settings
    ) -> SearchSnapshot | None:
        hit = self._cache.get(key)
        if hit is None:
            return None
        payload, age = hit
        try:
            snapshot = SearchSnapshot.model_validate_json(payload)
        except ValidationError:
            return None  # stored by an older version of the models: search again
        # The cache holds itineraries; transfers and rankings follow the settings of today.
        current = self._snapshot(
            query,
            snapshot.itineraries,
            snapshot.statuses,
            settings,
            snapshot.failed_origins,
            snapshot.calendar_entries,
            snapshot.calendar_note,
        )
        return current.model_copy(
            update={
                "completed_at": snapshot.completed_at,
                "from_cache": True,
                "cache_age_minutes": age,
            }
        )

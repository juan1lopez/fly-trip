"""Search orchestration: Kiwi explores, Google confirms, results stream out as events."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, ValidationError

from flytrip.core.candidates import DatePair, select_google_candidates
from flytrip.core.models import Itinerary
from flytrip.core.query import MENDOZA_TZ, SearchQuery
from flytrip.core.ranking import (
    apply_transfers,
    best_balance,
    best_per_origin,
    mark_separate_tickets,
    merge_duplicates,
    sort_by_total,
)
from flytrip.engine.cache import SearchCache
from flytrip.engine.settings import Settings
from flytrip.sources.base import PauseRegistry, Source, SourceRequest, SourceResult, run_safely
from flytrip.sources.google_flights import GOOGLE_FETCH_BUDGET
from flytrip.sources.kiwi import KIWI_MAX_WINDOW_DAYS

log = logging.getLogger("flytrip.search")

NO_DATES_DETAIL = "Sin fechas para confirmar"

SourceState = Literal["pending", "running", "ok", "paused", "error", "timeout", "skipped"]


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
        hard_timeout_s: float = 60,
    ) -> None:
        self.kiwi = kiwi
        self.google = google
        self._settings_provider = settings_provider
        self._cache = cache
        self._pauses = pauses
        self._clock = clock
        self._kiwi_timeout_s = kiwi_timeout_s
        self._google_timeout_s = google_timeout_s
        self._hard_timeout_s = hard_timeout_s
        self._cut_detail = f"La búsqueda se cortó a los {hard_timeout_s:g} s"

    async def aclose(self) -> None:
        for source in (self.kiwi, self.google):
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
        for status in statuses.values():
            yield StatusEvent(status=status)

        found, kiwi_status, cut = await self._explore(query, deadline)
        yield self._finish(kiwi_status, statuses, key)
        confirmed: list[Itinerary] = []
        google_status: SourceStatus | None
        if cut:
            google_status = SourceStatus(
                source=self.google.name, state="timeout", detail=self._cut_detail
            )
        else:
            yield SnapshotEvent(
                snapshot=self._snapshot(query, found, statuses, settings), final=False
            )
            pairs = select_google_candidates(found, query, GOOGLE_FETCH_BUDGET)
            google_status = self._google_hold(pairs)
            if google_status is None:
                running = SourceStatus(source=self.google.name, state="running")
                statuses[running.source] = running
                yield StatusEvent(status=running)
                confirmed, google_status = await self._confirm(query, pairs, deadline)
        yield self._finish(google_status, statuses, key)

        merged = merge_duplicates([*found, *confirmed])
        if not query.allow_separate_tickets:
            merged = [it for it in merged if it.separate_tickets is not True]
        final = self._snapshot(query, merged, statuses, settings)
        if any(status.state == "ok" for status in statuses.values()):
            self._cache.put(key, final.model_dump_json())
        yield SnapshotEvent(snapshot=final, final=True)

    async def _explore(
        self, query: SearchQuery, deadline: float
    ) -> tuple[list[Itinerary], SourceStatus, bool]:
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
        return found, self._summary(self.kiwi.name, outcomes, cut, len(found), started), cut

    async def _confirm(
        self, query: SearchQuery, pairs: Sequence[DatePair], deadline: float
    ) -> tuple[list[Itinerary], SourceStatus]:
        # All calls start together, so a per-call timeout of `google_timeout_s` bounds the
        # whole phase; the source's own semaphore keeps them at 3 at a time.
        started = time.monotonic()
        requests = [_google_request(pair, query) for pair in pairs]
        outcomes, cut = await self._call_all(
            self.google, requests, self._google_timeout_s, deadline
        )
        confirmed = [
            it for outcome in outcomes if outcome is not None for it in outcome.itineraries
        ]
        return confirmed, self._summary(self.google.name, outcomes, cut, len(confirmed), started)

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
        return [None if task.cancelled() else task.result() for task in tasks], bool(late)

    def _summary(
        self,
        name: str,
        outcomes: Sequence[SourceResult | None],
        cut: bool,
        count: int,
        started: float,
    ) -> SourceStatus:
        """One status for all the calls to a source: a block wins, then the cut, then success."""
        results = [outcome for outcome in outcomes if outcome is not None]
        latency_ms = int((time.monotonic() - started) * 1000)

        def status(state: SourceState, detail: str = "") -> SourceStatus:
            return SourceStatus(
                source=name, state=state, detail=detail, latency_ms=latency_ms, count=count
            )

        paused = next((r for r in results if r.status == "paused"), None)
        failed = next((r for r in results if r.status != "ok"), None)
        if paused is not None:
            return status("paused", paused.detail)
        if cut:
            return status("timeout", self._cut_detail)
        if failed is None or any(r.status == "ok" for r in results):
            return status("ok")
        return status(failed.status, failed.detail)

    def _google_hold(self, pairs: Sequence[DatePair]) -> SourceStatus | None:
        """Why Google is not called this time, or None when it should be."""
        pause = self._pauses.active_pause(self.google.name)
        if pause is not None:
            return SourceStatus(
                source=self.google.name, state="paused", detail=_pause_detail(*pause)
            )
        if not pairs:
            return SourceStatus(source=self.google.name, state="skipped", detail=NO_DATES_DETAIL)
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
    ) -> SearchSnapshot:
        ranked = sort_by_total(apply_transfers(itineraries, settings.transfers))
        return SearchSnapshot(
            query=query,
            itineraries=tuple(ranked),
            best_per_origin=best_per_origin(ranked, query.origins),
            best_balance=best_balance(ranked, settings.usd_per_hour),
            statuses=dict(statuses),
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
        current = self._snapshot(query, snapshot.itineraries, snapshot.statuses, settings)
        return current.model_copy(
            update={
                "completed_at": snapshot.completed_at,
                "from_cache": True,
                "cache_age_minutes": age,
            }
        )

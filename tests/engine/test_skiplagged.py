import asyncio
from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

import pytest

from flytrip.core.models import Offer
from flytrip.engine.search import SearchSnapshot
from flytrip.sources.base import SourceRequest, SourceResult
from flytrip.sources.skiplagged import CalendarResult
from tests.engine.conftest import A, build_engine, collect, google_answer, kiwi_answer
from tests.factories import FETCHED
from tests.factories import make_query as q
from tests.fakes import FakeSource

CalendarAnswer = Callable[[str, date], CalendarResult]


def ok_calendar(origin: str, anchor: date) -> CalendarResult:
    # Like the real tool: about 48 days, from anchor - 30 to anchor + 17; cheapest at anchor - 3.
    days = tuple(
        (anchor + timedelta(days=i), Decimal(970 + 10 * abs(i + 3))) for i in range(-30, 18)
    )
    return CalendarResult(source="skiplagged", status="ok", days=days)


class FakeSkiplagged(FakeSource):
    """Search answers like FakeSource; `calendar` answers per (origin, anchor)."""

    def __init__(
        self,
        results: Callable[[SourceRequest], SourceResult | Exception] | None = None,
        calendar: CalendarAnswer = ok_calendar,
    ) -> None:
        super().__init__("skiplagged", results or (lambda r: SourceResult("skiplagged", "ok")))
        self._calendar = calendar
        self.calendar_calls: list[tuple[str, str, date, date | None]] = []

    async def calendar(
        self, origin: str, destination: str, anchor: date, return_date: date | None
    ) -> CalendarResult:
        self.calendar_calls.append((origin, destination, anchor, return_date))
        return self._calendar(origin, anchor)


def _engine(tmp_path, clock, pauses, skiplagged, **kw):
    return build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", kiwi_answer()),
        google=FakeSource("google", google_answer()),
        skiplagged=skiplagged,
        **kw,
    )


def _skiplagged_hit(request: SourceRequest) -> SourceResult:
    base = google_answer()(request)
    assert isinstance(base, SourceResult)
    itineraries = tuple(
        it.model_copy(
            update={
                "id": it.id.replace("G-", "S-"),
                "offers": (it.best_offer.model_copy(update={"source": "skiplagged"}),),
            }
        )
        for it in base.itineraries
    )
    return SourceResult("skiplagged", "ok", itineraries=itineraries, fetches=1)


async def test_skiplagged_gets_google_pairs_within_its_budget(tmp_path, clock, pauses):
    sk = FakeSkiplagged(_skiplagged_hit)
    engine = _engine(tmp_path, clock, pauses, sk)
    final = (await collect(engine.run(q())))[-1].snapshot
    pairs = [(r.origin, r.depart_from, r.nights_min) for r in sk.calls]
    google_pairs = [(r.origin, r.depart_from, r.nights_min) for r in engine.google.calls]
    assert 0 < len(pairs) <= 12
    assert set(google_pairs) <= set(pairs)
    assert final.statuses["skiplagged"].state == "ok"
    assert {"S-MDZ-2027-03-10"} & {i.id for i in final.itineraries}


async def test_calendar_runs_only_in_month_mode(tmp_path, clock, pauses):
    sk = FakeSkiplagged(_skiplagged_hit)
    engine = _engine(tmp_path, clock, pauses, sk)
    plain = (await collect(engine.run(q())))[-1].snapshot
    assert sk.calendar_calls == [] and plain.calendar == ()
    month = (await collect(engine.run(q(calendar=True))))[-1].snapshot
    assert len(sk.calendar_calls) == 6  # 3 origins x 2 calls for 3 months
    assert month.calendar and month.calendar_note == ""


async def test_calendar_anchors_start_30_days_in_and_continue_after_the_last_day(
    tmp_path, clock, pauses
):
    sk = FakeSkiplagged()
    engine = _engine(tmp_path, clock, pauses, sk)
    query = q(calendar=True, origins=("EZE",), depart_from=date(2027, 3, 20), nights_min=14)
    await collect(engine.run(query))
    # First call covers Mar 20 - May 6 (anchor - 30 .. anchor + 17); the next starts at May 7.
    assert sk.calendar_calls == [
        ("EZE", "MAD", date(2027, 4, 19), date(2027, 5, 3)),
        ("EZE", "MAD", date(2027, 6, 6), date(2027, 6, 20)),
    ]


async def test_calendar_stops_once_the_window_is_covered(tmp_path, clock, pauses):
    sk = FakeSkiplagged()
    engine = _engine(tmp_path, clock, pauses, sk)
    query = q(calendar=True, origins=("EZE",), depart_to=date(2027, 3, 31))
    await collect(engine.run(query))
    assert [c[2] for c in sk.calendar_calls] == [date(2027, 3, 31)]


async def test_calendar_makes_at_most_three_calls_per_origin(tmp_path, clock, pauses):
    def short(origin: str, anchor: date) -> CalendarResult:
        days = tuple((anchor + timedelta(days=i), Decimal(1000)) for i in range(-30, -20))
        return CalendarResult("skiplagged", "ok", days=days)

    sk = FakeSkiplagged(calendar=short)
    engine = _engine(tmp_path, clock, pauses, sk)
    await collect(engine.run(q(calendar=True, origins=("EZE",))))
    assert len(sk.calendar_calls) == 3


@pytest.mark.parametrize("oneway", [False, True])
@pytest.mark.parametrize(("last_month", "expected"), [(3, 7), (5, 10), (6, 12)])
async def test_skiplagged_calls_per_search_are_pinned(
    tmp_path, clock, pauses, oneway, last_month, expected
):
    # 3 origins, Kiwi found nothing (so every origin falls back to its own date pairs):
    # 1 month = 3 calendar + 4 pairs, 3 months = 6 + 4, 4 months = 9 + 3 (the cap is 12).
    sk = FakeSkiplagged(_skiplagged_hit)
    engine = build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", lambda r: SourceResult("kiwi", "ok")),
        google=FakeSource("google", google_answer()),
        skiplagged=sk,
    )
    last_day = {3: 31, 5: 31, 6: 30}[last_month]
    query = q(
        calendar=True,
        depart_to=date(2027, last_month, last_day),
        nights_min=None if oneway else 14,
        nights_max=None if oneway else 21,
    )
    await collect(engine.run(query))
    assert len(sk.calendar_calls) + len(sk.calls) == expected
    assert len(sk.calendar_calls) + len(sk.calls) <= 12


async def test_search_without_month_mode_confirms_four_pairs(tmp_path, clock, pauses):
    sk = FakeSkiplagged(_skiplagged_hit)
    engine = _engine(tmp_path, clock, pauses, sk)
    await collect(engine.run(q()))
    assert sk.calendar_calls == [] and 0 < len(sk.calls) <= 4


async def test_calendar_keeps_days_in_window_and_adds_transfer(tmp_path, clock, pauses):
    sk = FakeSkiplagged()
    engine = _engine(tmp_path, clock, pauses, sk)
    query = q(
        calendar=True, origins=("EZE",), depart_from=date(2027, 3, 1), depart_to=date(2027, 3, 31)
    )
    snap = (await collect(engine.run(query)))[-1].snapshot
    assert all(date(2027, 3, 1) <= d.day <= date(2027, 3, 31) for d in snap.calendar)
    # EZE transfer is 200 USD round trip in the test settings; the cheapest base price is 970.
    assert min(d.price_usd for d in snap.calendar) == Decimal("1170")


async def test_skiplagged_failure_keeps_kiwi_and_google(tmp_path, clock, pauses):
    sk = FakeSkiplagged(lambda r: SourceResult("skiplagged", "error", detail="Skiplagged: roto"))
    engine = _engine(tmp_path, clock, pauses, sk)
    final = (await collect(engine.run(q())))[-1].snapshot
    assert final.statuses["skiplagged"].state == "error"
    assert final.statuses["kiwi"].state == final.statuses["google"].state == "ok"
    assert {"SELF", "PROT", "A", "C"} <= {i.id for i in final.itineraries}


async def test_skiplagged_partial_status(tmp_path, clock, pauses):
    def answer(r: SourceRequest) -> SourceResult:
        if r.origin == "MDZ":
            return SourceResult("skiplagged", "error", detail="roto")
        return _skiplagged_hit(r)

    engine = _engine(tmp_path, clock, pauses, FakeSkiplagged(answer))
    final = (await collect(engine.run(q())))[-1].snapshot
    assert final.statuses["skiplagged"].state == "partial"


async def test_skiplagged_all_empty_is_a_block_and_pauses(tmp_path, clock, pauses):
    engine = _engine(tmp_path, clock, pauses, FakeSkiplagged())
    final = (await collect(engine.run(q())))[-1].snapshot
    assert final.statuses["skiplagged"].state == "error"
    assert "posible bloqueo" in final.statuses["skiplagged"].detail
    assert pauses.active_pause("skiplagged") is not None
    again = (await collect(engine.run(q(), use_cache=False)))[-1].snapshot
    assert again.statuses["skiplagged"].state == "paused"


async def test_paused_skiplagged_is_not_called(tmp_path, clock, pauses):
    pauses.pause("skiplagged", 60, "429")
    sk = FakeSkiplagged()
    engine = _engine(tmp_path, clock, pauses, sk)
    final = (await collect(engine.run(q(calendar=True))))[-1].snapshot
    assert sk.calls == [] and sk.calendar_calls == []
    assert final.statuses["skiplagged"].state == "paused"
    assert final.calendar_note.startswith("Calendario no disponible")


async def test_calendar_unavailable_when_every_call_fails(tmp_path, clock, pauses):
    def broken(origin: str, anchor: date) -> CalendarResult:
        return CalendarResult("skiplagged", "error", detail="Skiplagged: sin datos")

    sk = FakeSkiplagged(_skiplagged_hit, calendar=broken)
    engine = _engine(tmp_path, clock, pauses, sk)
    final = (await collect(engine.run(q(calendar=True))))[-1].snapshot
    assert final.calendar == ()
    assert final.calendar_note == "Calendario no disponible: Skiplagged: sin datos"
    assert final.statuses["kiwi"].state == "ok" and final.itineraries


async def test_calendar_exception_never_breaks_the_search(tmp_path, clock, pauses):
    class Exploding(FakeSkiplagged):
        async def calendar(self, *args, **kwargs):
            raise RuntimeError("boom")

    engine = _engine(tmp_path, clock, pauses, Exploding(_skiplagged_hit))
    final = (await collect(engine.run(q(calendar=True))))[-1].snapshot
    assert final.calendar_note.startswith("Calendario no disponible")
    assert final.itineraries


async def test_same_flight_from_kiwi_and_skiplagged_merges_into_two_offers(tmp_path, clock, pauses):
    def same_as_kiwi(request: SourceRequest) -> SourceResult:
        if request.origin != "SCL":
            return SourceResult("skiplagged", "ok")
        offer = Offer(
            source="skiplagged",
            price_usd=Decimal("700"),
            booking_url="https://skiplagged.example/x",
            fetched_at=FETCHED,
        )
        return SourceResult(
            "skiplagged", "ok", itineraries=(A.model_copy(update={"offers": (offer,)}),)
        )

    engine = _engine(tmp_path, clock, pauses, FakeSkiplagged(same_as_kiwi))
    final = (await collect(engine.run(q())))[-1].snapshot
    rows = [i for i in final.itineraries if i.id == "A"]
    assert len(rows) == 1
    assert {o.source for o in rows[0].offers} == {"kiwi", "skiplagged"}


async def test_cached_snapshot_rebuilds_calendar_with_current_transfers(tmp_path, clock, pauses):
    from flytrip.engine.settings import Settings
    from tests.factories import T

    transfers = {"EZE": T("200", "2")}
    sk = FakeSkiplagged(_skiplagged_hit)
    engine = _engine(
        tmp_path, clock, pauses, sk, settings=lambda: Settings(transfers=dict(transfers))
    )
    query = q(calendar=True, origins=("EZE",))
    first = (await collect(engine.run(query)))[-1].snapshot
    transfers["EZE"] = T("50", "2")
    [hit] = await collect(engine.run(query))
    assert hit.snapshot.from_cache
    delta = min(d.price_usd for d in first.calendar) - min(
        d.price_usd for d in hit.snapshot.calendar
    )
    assert delta == Decimal("150")


def test_old_cached_snapshot_without_calendar_fields_still_validates():
    snap = SearchSnapshot.model_validate_json(
        SearchSnapshot(
            query=q(),
            itineraries=(),
            best_per_origin={},
            best_balance=None,
            statuses={},
            completed_at=FETCHED,
        ).model_dump_json(exclude={"calendar", "calendar_note", "calendar_entries"})
    )
    assert snap.calendar == () and snap.calendar_note == ""


async def test_failed_calendar_is_not_cached(tmp_path, clock, pauses):
    def broken(origin: str, anchor: date) -> CalendarResult:
        return CalendarResult("skiplagged", "error", detail="roto")

    sk = FakeSkiplagged(_skiplagged_hit, calendar=broken)
    engine = _engine(tmp_path, clock, pauses, sk)
    await collect(engine.run(q(calendar=True)))
    again = await collect(engine.run(q(calendar=True)))
    assert not again[-1].snapshot.from_cache and len(sk.calendar_calls) == 6


async def test_empty_calendar_carries_a_note(tmp_path, clock, pauses):
    def empty(origin: str, anchor: date) -> CalendarResult:
        return CalendarResult("skiplagged", "ok", days=())

    engine = _engine(tmp_path, clock, pauses, FakeSkiplagged(_skiplagged_hit, calendar=empty))
    final = (await collect(engine.run(q(calendar=True))))[-1].snapshot
    assert final.calendar_note == "Calendario no disponible: sin datos"


async def test_calendar_prices_are_scaled_by_adults(tmp_path, clock, pauses):
    engine = _engine(tmp_path, clock, pauses, FakeSkiplagged(_skiplagged_hit))
    query = q(calendar=True, origins=("EZE",), adults=2)
    snap = (await collect(engine.run(query)))[-1].snapshot
    # Base cheapest is 970 per person; EZE transfer (200) is added once, after the multiplication.
    assert min(d.price_usd for d in snap.calendar) == Decimal("2140")


async def test_each_source_status_streams_when_it_finishes(tmp_path, clock, pauses):
    from flytrip.engine.search import StatusEvent

    sk = FakeSkiplagged(_skiplagged_hit)
    engine = build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", kiwi_answer()),
        google=FakeSource("google", google_answer(), delay_s=0.4),
        skiplagged=sk,
    )
    stamps: dict[str, float] = {}
    import time

    async for event in engine.run(q()):
        if isinstance(event, StatusEvent) and event.status.state == "ok":
            stamps[event.status.source] = time.monotonic()
    assert stamps["google"] - stamps["skiplagged"] > 0.2


class SlowCalendar(FakeSkiplagged):
    def __init__(self, delay_s: float, results=None, calendar: CalendarAnswer = ok_calendar):
        super().__init__(results, calendar)
        self._delay_s = delay_s

    async def calendar(self, origin, destination, anchor, return_date):
        await asyncio.sleep(self._delay_s)
        return await super().calendar(origin, destination, anchor, return_date)


async def test_calendar_cut_by_the_deadline_keeps_what_arrived(tmp_path, clock, pauses):
    # 2 calls per origin at 0.2 s each; the 0.3 s hard cut lands between them.
    sk = SlowCalendar(0.2, _skiplagged_hit)
    engine = _engine(tmp_path, clock, pauses, sk, hard_timeout_s=0.3)
    final = (await collect(engine.run(q(calendar=True))))[-1].snapshot
    assert final.calendar
    assert final.calendar_note.startswith("Calendario incompleto: falló MDZ (")
    assert "se cortó a los 0.3 s" in final.calendar_note
    assert len(sk.calendar_calls) == 3  # the second call of each origin was cut mid-flight


async def test_partial_calendar_says_which_origin_failed_and_is_not_cached(tmp_path, clock, pauses):
    def eze_broken(origin: str, anchor: date) -> CalendarResult:
        if origin == "EZE":
            return CalendarResult("skiplagged", "error", detail="Skiplagged: roto")
        return ok_calendar(origin, anchor)

    sk = FakeSkiplagged(_skiplagged_hit, calendar=eze_broken)
    engine = _engine(tmp_path, clock, pauses, sk)
    final = (await collect(engine.run(q(calendar=True))))[-1].snapshot
    assert final.calendar
    assert final.calendar_note == "Calendario incompleto: falló EZE (Skiplagged: roto)"
    again = (await collect(engine.run(q(calendar=True))))[-1].snapshot
    assert not again.from_cache


async def test_interim_snapshot_marks_a_calendar_still_loading(tmp_path, clock, pauses):
    from flytrip.engine.search import SnapshotEvent

    engine = _engine(tmp_path, clock, pauses, SlowCalendar(0.3, _skiplagged_hit))
    snapshots = [
        e.snapshot async for e in engine.run(q(calendar=True)) if isinstance(e, SnapshotEvent)
    ]
    interim, final = snapshots[0], snapshots[-1]
    assert interim.calendar_pending and interim.calendar == ()
    assert not final.calendar_pending and final.calendar


async def test_snapshot_without_month_mode_is_never_pending(tmp_path, clock, pauses):
    engine = _engine(tmp_path, clock, pauses, FakeSkiplagged(_skiplagged_hit))
    final = (await collect(engine.run(q())))[-1].snapshot
    assert not final.calendar_pending


async def test_skiplagged_soft_deadline_keeps_what_finished(tmp_path, clock, pauses):
    class Mixed(FakeSkiplagged):
        async def search(self, request: SourceRequest) -> SourceResult:
            if request.origin != "MDZ":
                await asyncio.sleep(5)
            return await super().search(request)

    engine = _engine(
        tmp_path, clock, pauses, Mixed(_skiplagged_hit), skiplagged_soft_deadline_s=0.2
    )
    final = (await collect(engine.run(q())))[-1].snapshot
    status = final.statuses["skiplagged"]
    assert status.state == "partial" and status.detail == "se cortó a los 0.2 s"
    assert final.statuses["google"].state == "ok"


async def test_skiplagged_soft_deadline_with_nothing_finished_is_a_timeout(tmp_path, clock, pauses):
    engine = _engine(
        tmp_path,
        clock,
        pauses,
        SlowCalendar(0, _skiplagged_hit),
        skiplagged_soft_deadline_s=0.2,
    )

    async def never(request: SourceRequest) -> SourceResult:
        await asyncio.sleep(5)
        return SourceResult("skiplagged", "ok")

    engine.skiplagged.search = never  # type: ignore[union-attr, method-assign]
    final = (await collect(engine.run(q())))[-1].snapshot
    assert final.statuses["skiplagged"].state == "timeout"


async def test_itineraries_that_leave_from_another_origin_are_dropped(tmp_path, clock, pauses):
    from tests.factories import itin_on

    scl_trip = itin_on("SCL", "2027-03-12", "2027-03-27", 100).model_copy(update={"id": "WRONG"})

    def replay(request: SourceRequest) -> SourceResult:
        # Like a replay that answers every origin with the same recorded SCL trip.
        trip = scl_trip.model_copy(update={"origin": request.origin})
        return SourceResult("skiplagged", "ok", itineraries=(trip,), fetches=1)

    engine = _engine(tmp_path, clock, pauses, FakeSkiplagged(replay))
    final = (await collect(engine.run(q())))[-1].snapshot
    # Only the SCL request may keep the recorded SCL trip.
    assert {i.origin for i in final.itineraries if i.id == "WRONG"} == {"SCL"}
    assert all(i.outbound.segments[0].from_airport == i.origin for i in final.itineraries)
    status = final.statuses["skiplagged"]
    assert "Se descartaron 3 resultados" in status.detail
    assert status.state == "ok"  # dropping answers is not a block


async def test_kiwi_results_are_checked_against_the_origin_too(tmp_path, clock, pauses):
    from tests.factories import itin_on

    wrong = itin_on("EZE", "2027-03-12", "2027-03-27", 100).model_copy(
        update={"id": "WRONG", "origin": "SCL"}
    )

    def kiwi(request: SourceRequest) -> SourceResult:
        found = (wrong,) if request.origin == "SCL" else ()
        return SourceResult("kiwi", "ok", itineraries=found, fetches=1)

    engine = build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", kiwi),
        google=FakeSource("google", google_answer()),
    )
    final = (await collect(engine.run(q())))[-1].snapshot
    assert "WRONG" not in {i.id for i in final.itineraries}
    assert "descartaron" in final.statuses["kiwi"].detail


async def test_cards_all_dropped_by_the_source_are_not_a_silent_block(tmp_path, clock, pauses):
    def all_dropped(request: SourceRequest) -> SourceResult:
        return SourceResult("skiplagged", "ok", fetches=1, raw_count=5, dropped=5)

    engine = _engine(tmp_path, clock, pauses, FakeSkiplagged(all_dropped))
    final = (await collect(engine.run(q())))[-1].snapshot
    status = final.statuses["skiplagged"]
    assert status.state == "ok" and "descartaron" in status.detail
    assert pauses.active_pause("skiplagged") is None

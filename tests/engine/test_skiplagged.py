from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal

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
    days = tuple((anchor + timedelta(days=i), Decimal(1000 + 10 * i)) for i in range(-3, 4))
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
    assert len(sk.calendar_calls) == 9  # 3 origins x 3 months
    assert month.calendar and month.calendar_note == ""


async def test_calendar_anchors_on_15th_or_window_start(tmp_path, clock, pauses):
    sk = FakeSkiplagged()
    engine = _engine(tmp_path, clock, pauses, sk)
    query = q(calendar=True, origins=("EZE",), depart_from=date(2027, 3, 20), nights_min=14)
    await collect(engine.run(query))
    assert sk.calendar_calls == [
        ("EZE", "MAD", date(2027, 3, 20), date(2027, 4, 3)),
        ("EZE", "MAD", date(2027, 4, 15), date(2027, 4, 29)),
        ("EZE", "MAD", date(2027, 5, 15), date(2027, 5, 29)),
    ]


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
    assert not again[-1].snapshot.from_cache and len(sk.calendar_calls) == 18


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

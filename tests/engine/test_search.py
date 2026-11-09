import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest

from flytrip.engine.search import SnapshotEvent, StatusEvent
from flytrip.engine.settings import Settings
from flytrip.sources.base import SourceRequest, SourceResult
from tests.engine.conftest import build_engine, collect, google_answer, kiwi_answer
from tests.factories import T, itin_on
from tests.factories import make_query as q
from tests.fakes import FakeSource


# google fake con delay 0.3 s
async def test_kiwi_snapshot_arrives_before_google_finishes(engine):
    events = [e async for e in engine.run(q())]
    first_partial = next(
        i for i, e in enumerate(events) if isinstance(e, SnapshotEvent) and not e.final
    )
    google_done = next(
        i
        for i, e in enumerate(events)
        if isinstance(e, StatusEvent)
        and e.status.source == "google"
        and e.status.state not in {"pending", "running"}
    )
    assert (
        first_partial < google_done and isinstance(events[-1], SnapshotEvent) and events[-1].final
    )


async def test_separate_tickets_from_two_kiwi_modes(engine):
    final = (await collect(engine.run(q())))[-1].snapshot
    assert {i.id: i.separate_tickets for i in final.itineraries if i.id in {"SELF", "PROT"}} == {
        "SELF": True,
        "PROT": False,
    }


async def test_disallowing_separate_tickets(engine):
    final = (await collect(engine.run(q(allow_separate_tickets=False))))[-1].snapshot
    assert (
        all(r.allow_separate_tickets is False for r in engine.kiwi.calls)
        and len(engine.kiwi.calls) == 3
    )
    assert all(i.separate_tickets is not True for i in final.itineraries)


async def test_google_calls_stay_within_budget(engine):
    await collect(engine.run(q()))
    assert sum(2 if r.nights_min else 1 for r in engine.google.calls) <= 12


async def test_paused_google_is_not_called(engine, pauses):
    pauses.pause("google", 60, "429")
    final = (await collect(engine.run(q())))[-1].snapshot
    assert engine.google.calls == [] and final.statuses["google"].state == "paused"


# hard_timeout_s=0.2, kiwi con delay 5 s
async def test_hard_timeout_marks_pending_sources(slow_engine):
    final = (await collect(slow_engine.run(q())))[-1].snapshot
    assert final.statuses["kiwi"].state == "timeout"


async def test_cache_hit_and_expiry(engine, clock):
    await collect(engine.run(q()))
    calls = len(engine.kiwi.calls)
    clock.advance(minutes=10)
    [only] = await collect(engine.run(q()))
    assert (
        only.snapshot.from_cache
        and only.snapshot.cache_age_minutes == 10
        and len(engine.kiwi.calls) == calls
    )
    clock.advance(minutes=21)
    await collect(engine.run(q()))
    assert len(engine.kiwi.calls) > calls


async def test_transfers_and_empty_origin(engine_without_eze_results):
    final = (await collect(engine_without_eze_results.run(q())))[-1].snapshot
    assert final.best_per_origin["EZE"] is None
    # ajustes: SCL = T("80", "7")
    assert final.best_per_origin["SCL"].total_from_home_usd == Decimal("838")


async def test_logs_one_record_per_source(engine, caplog):
    caplog.set_level("INFO", logger="flytrip.search")
    await collect(engine.run(q()))
    assert sorted(r.source for r in caplog.records if r.msg == "source_done") == ["google", "kiwi"]


def _error(source: str, detail: str) -> SourceResult:
    return SourceResult(source=source, status="error", detail=detail)


async def test_google_errors_keep_kiwi_results(tmp_path, clock, pauses):
    google = FakeSource("google", lambda r: _error("google", f"Falla {r.origin} {r.depart_from}"))
    engine = build_engine(
        tmp_path, clock, pauses, kiwi=FakeSource("kiwi", kiwi_answer()), google=google
    )
    final = (await collect(engine.run(q())))[-1].snapshot
    status = final.statuses["google"]
    # The first pair is MDZ's cheapest (SELF); the last one is MDZ's PROT.
    assert len(google.calls) == 4
    assert (status.state, status.detail) == ("error", "Falla MDZ 2027-03-10")
    assert final.statuses["kiwi"].state == "ok"
    assert {i.id for i in final.itineraries} == {"SELF", "PROT", "A", "C"}


async def test_hard_timeout_during_kiwi_never_calls_google(slow_engine):
    events = await collect(slow_engine.run(q()))
    statuses = events[-1].snapshot.statuses
    assert events[-1].final and slow_engine.google.calls == []
    assert not any(isinstance(e, SnapshotEvent) and not e.final for e in events)
    assert statuses["google"].state == "timeout"
    assert statuses["kiwi"].detail == "La búsqueda se cortó a los 0.2 s"


async def test_cancelled_search_leaves_no_source_calls_running(slow_engine):
    search = asyncio.create_task(collect(slow_engine.run(q())))
    await asyncio.sleep(0.05)
    search.cancel()
    with pytest.raises(asyncio.CancelledError):
        await search
    assert asyncio.all_tasks() == {asyncio.current_task()}


async def test_google_confirms_exact_dates_from_kiwi(tmp_path, clock, pauses):
    google = FakeSource("google", google_answer())
    engine = build_engine(
        tmp_path, clock, pauses, kiwi=FakeSource("kiwi", kiwi_answer()), google=google
    )
    await collect(engine.run(q(adults=2)))
    expected = SourceRequest(
        origin="MDZ",
        destination="MAD",
        depart_from=date(2027, 3, 10),
        depart_to=date(2027, 3, 10),
        nights_min=15,
        nights_max=15,
        adults=2,
        allow_separate_tickets=True,
    )
    assert expected in google.calls


async def test_google_is_skipped_without_candidate_dates(tmp_path, clock, pauses):
    kiwi = FakeSource("kiwi", lambda r: SourceResult(source="kiwi", status="ok"))
    google = FakeSource("google", google_answer())
    engine = build_engine(tmp_path, clock, pauses, kiwi=kiwi, google=google)
    final = (await collect(engine.run(q(destination="Madrid"))))[-1].snapshot
    status = final.statuses["google"]
    assert google.calls == []
    assert (status.state, status.detail) == ("skipped", "Sin fechas para confirmar")


@pytest.mark.parametrize("timeouts", [{"google_timeout_s": 0.1}, {"hard_timeout_s": 0.2}])
async def test_slow_google_is_cut_and_kiwi_results_stay(tmp_path, clock, pauses, timeouts):
    google = FakeSource("google", google_answer(), delay_s=5)
    engine = build_engine(
        tmp_path, clock, pauses, kiwi=FakeSource("kiwi", kiwi_answer()), google=google, **timeouts
    )
    events = await collect(engine.run(q()))
    final = events[-1].snapshot
    assert events[-1].final and final.statuses["google"].state == "timeout"
    assert final.statuses["kiwi"].state == "ok"
    assert {i.id for i in final.itineraries} == {"SELF", "PROT", "A", "C"}


async def test_search_without_any_ok_source_is_not_cached(tmp_path, clock, pauses):
    kiwi = FakeSource("kiwi", lambda r: _error("kiwi", "Kiwi respondió 500"))
    google = FakeSource("google", lambda r: _error("google", "Google respondió 500"))
    engine = build_engine(tmp_path, clock, pauses, kiwi=kiwi, google=google)
    first = (await collect(engine.run(q())))[-1].snapshot
    await collect(engine.run(q()))
    assert first.statuses["kiwi"].state == "error" and len(kiwi.calls) == 12


async def test_cached_snapshot_matches_fresh_one_and_refresh_skips_cache(tmp_path, clock, pauses):
    kiwi = FakeSource("kiwi", kiwi_answer())
    engine = build_engine(
        tmp_path, clock, pauses, kiwi=kiwi, google=FakeSource("google", google_answer())
    )
    fresh = (await collect(engine.run(q())))[-1].snapshot
    [hit] = await collect(engine.run(q()))
    assert hit.final and hit.snapshot.from_cache
    assert hit.snapshot.model_copy(update={"from_cache": False, "cache_age_minutes": None}) == fresh
    await collect(engine.run(q(), use_cache=False))
    assert len(kiwi.calls) == 12


async def test_failed_protected_mode_leaves_separate_tickets_unknown(tmp_path, clock, pauses):
    full = kiwi_answer()

    def kiwi(request):
        if request.origin == "MDZ" and not request.allow_separate_tickets:
            return _error("kiwi", "Kiwi respondió 500")
        return full(request)

    engine = build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", kiwi),
        google=FakeSource("google", google_answer()),
    )
    final = (await collect(engine.run(q())))[-1].snapshot
    kiwi_status = final.statuses["kiwi"]
    assert (kiwi_status.state, kiwi_status.detail) == ("partial", "falló MDZ: Kiwi respondió 500")
    assert final.failed_origins == {}
    assert {i.id: i.separate_tickets for i in final.itineraries if i.id in {"SELF", "PROT"}} == {
        "SELF": None,
        "PROT": None,
    }


async def test_protected_only_results_are_kept(tmp_path, clock, pauses):
    extra = itin_on("MDZ", "2027-04-01", "2027-04-15", 1100).model_copy(update={"id": "EXTRA"})
    full = kiwi_answer()

    def kiwi(request):
        result = full(request)
        if request.origin == "MDZ" and not request.allow_separate_tickets:
            return replace(result, itineraries=(*result.itineraries, extra))
        return result

    engine = build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", kiwi),
        google=FakeSource("google", google_answer()),
    )
    final = (await collect(engine.run(q())))[-1].snapshot
    marks = {i.id: i.separate_tickets for i in final.itineraries if i.origin == "MDZ"}
    assert {k: marks[k] for k in ("SELF", "PROT", "EXTRA")} == {
        "SELF": True,
        "PROT": False,
        "EXTRA": False,
    }


async def test_settings_saved_after_a_search_apply_to_the_cached_result(tmp_path, clock, pauses):
    current = {"settings": Settings(transfers={"SCL": T("80", "7"), "EZE": T("200", "2")})}
    engine = build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", kiwi_answer()),
        google=FakeSource("google", google_answer()),
        settings=lambda: current["settings"],
    )
    fresh = (await collect(engine.run(q())))[-1].snapshot
    assert fresh.best_per_origin["SCL"].total_from_home_usd == Decimal("838")
    current["settings"] = Settings(
        transfers={"SCL": T("500", "7"), "EZE": T("200", "2")}, usd_per_hour=Decimal("0")
    )
    [hit] = await collect(engine.run(q()))
    snapshot = hit.snapshot
    assert snapshot.from_cache and snapshot.cache_age_minutes == 0
    assert snapshot.completed_at == fresh.completed_at
    assert snapshot.best_per_origin["SCL"].total_from_home_usd == Decimal("1258")
    assert snapshot.best_balance == min(
        snapshot.itineraries, key=lambda i: (i.total_from_home_usd, i.id)
    )
    totals = [i.total_from_home_usd for i in snapshot.itineraries]
    assert totals == sorted(totals)


async def test_origin_failing_in_every_call_is_reported_and_status_is_partial(
    tmp_path, clock, pauses
):
    full = kiwi_answer()

    def kiwi(request):
        if request.origin == "EZE":
            return _error("kiwi", "Kiwi respondió 500")
        return full(request)

    engine = build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", kiwi),
        google=FakeSource("google", google_answer(eze=False)),
    )
    final = (await collect(engine.run(q())))[-1].snapshot
    assert final.statuses["kiwi"].state == "partial"
    assert final.statuses["kiwi"].detail == "falló EZE: Kiwi respondió 500"
    assert final.failed_origins == {"EZE": "Kiwi respondió 500"}
    assert final.best_per_origin["EZE"] is None
    [hit] = await collect(engine.run(q()))
    assert hit.snapshot.from_cache and hit.snapshot.failed_origins == final.failed_origins


async def test_all_kiwi_calls_ok_stay_ok_without_failed_origins(engine):
    final = (await collect(engine.run(q())))[-1].snapshot
    assert final.statuses["kiwi"].state == "ok" and final.failed_origins == {}


async def test_google_returning_nothing_for_every_date_is_reported_as_a_block(
    tmp_path, clock, pauses
):
    google = FakeSource("google", lambda r: SourceResult(source="google", status="ok", fetches=2))
    engine = build_engine(
        tmp_path, clock, pauses, kiwi=FakeSource("kiwi", kiwi_answer()), google=google
    )
    final = (await collect(engine.run(q())))[-1].snapshot
    status = final.statuses["google"]
    reason = "Google no devolvió resultados para ninguna fecha (posible bloqueo)"
    assert (status.state, status.detail) == ("error", reason)
    assert pauses.active_pause("google") is not None
    assert pauses.active_pause("google")[1] == reason
    calls = len(google.calls)
    again = (await collect(engine.run(q(), use_cache=False)))[-1].snapshot
    assert len(google.calls) == calls and again.statuses["google"].state == "paused"


async def test_google_with_some_results_is_not_a_block(engine_without_eze_results, pauses):
    final = (await collect(engine_without_eze_results.run(q())))[-1].snapshot
    assert final.statuses["google"].state == "ok"
    assert pauses.active_pause("google") is None

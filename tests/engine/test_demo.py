from datetime import date

from flytrip.devtools import demo
from flytrip.devtools.demo import build_demo_engine
from tests.engine.conftest import collect
from tests.factories import make_query as q


async def test_demo_engine_produces_calendar_and_skiplagged_status(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "GOOGLE_DELAY_S", 0)
    monkeypatch.setattr(demo, "SKIPLAGGED_DELAY_S", 0)
    engine = build_demo_engine(tmp_path)
    query = q(calendar=True, depart_from=date(2027, 3, 1), depart_to=date(2027, 5, 31))
    final = (await collect(engine.run(query)))[-1].snapshot
    assert final.statuses["skiplagged"].state == "ok"
    assert final.calendar_note == "" and final.calendar
    assert {d.day.month for d in final.calendar} == {3, 4, 5}
    assert any(any(o.source == "skiplagged" for o in it.offers) for it in final.itineraries)
    await engine.aclose()


async def test_demo_itineraries_only_come_from_the_origin_they_leave(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "GOOGLE_DELAY_S", 0)
    monkeypatch.setattr(demo, "SKIPLAGGED_DELAY_S", 0)
    engine = build_demo_engine(tmp_path)
    query = q(depart_from=date(2027, 3, 1), depart_to=date(2027, 5, 31))
    final = (await collect(engine.run(query)))[-1].snapshot
    assert final.itineraries
    for it in final.itineraries:
        assert it.outbound.segments[0].from_airport == it.origin
        assert it.inbound is not None and it.inbound.segments[-1].to_airport == it.origin
    assert final.best_per_origin["MDZ"] is not None
    assert all(s.state == "ok" for s in final.statuses.values())
    await engine.aclose()


async def test_demo_search_from_an_origin_without_fixtures_is_not_a_block(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "GOOGLE_DELAY_S", 0)
    monkeypatch.setattr(demo, "SKIPLAGGED_DELAY_S", 0)
    engine = build_demo_engine(tmp_path)
    query = q(origins=("MDZ",), depart_from=date(2027, 3, 1), depart_to=date(2027, 5, 31))
    final = (await collect(engine.run(query)))[-1].snapshot
    assert final.statuses["google"].state == "ok" and final.statuses["skiplagged"].state == "ok"
    await engine.aclose()

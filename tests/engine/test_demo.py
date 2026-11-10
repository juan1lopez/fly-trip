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

from datetime import date
from decimal import Decimal
from html import unescape

from fastapi.testclient import TestClient

from flytrip.core.calendar import CalendarDay
from flytrip.web.app import create_app
from flytrip.web.views import calendar_months
from tests.factories import make_query
from tests.fakes import LOCAL_URL, SNAPSHOT_A_B_C, StaticEngine
from tests.web.conftest import sse_events

QS = (
    "destino=MAD&desde=2027-03-01&hasta=2027-05-31&noches_min=14&noches_max=21"
    "&origenes=MDZ&origenes=SCL&origenes=EZE&adultos=1&separados=1"
)
MONTH_QS = (
    "modo=mes&destino=MAD&mes=2027-03&hasta_mes=2027-04&noches_min=14&noches_max=21"
    "&origenes=MDZ&origenes=SCL&adultos=1"
)


def _results(client, qs):
    return "".join(d for e, d in sse_events(client, "/buscar/stream?" + qs) if e == "results")


def calendar_snapshot(days, note=""):
    return SNAPSHOT_A_B_C.model_copy(
        update={
            "query": make_query(
                calendar=True, depart_from=date(2027, 3, 10), depart_to=date(2027, 4, 20)
            ),
            "calendar": tuple(
                CalendarDay(day=date.fromisoformat(d), price_usd=Decimal(p), origin=o)
                for d, p, o in days
            ),
            "calendar_note": note,
        }
    )


def recording_client(settings_store, snapshot=None):
    queries = []

    class Recording(StaticEngine):
        async def run(self, query, *, use_cache=True):
            queries.append(query)
            async for event in super().run(query, use_cache=use_cache):
                yield event

    engine = Recording(snapshot or SNAPSHOT_A_B_C)
    app = create_app(engine_factory=lambda: engine, settings_store=settings_store)
    return TestClient(app, base_url=LOCAL_URL), queries


# -- views -------------------------------------------------------------------------------


def test_calendar_months_cover_the_query_window_and_mark_cheap_days():
    days = [("2027-03-12", "900", "MDZ"), ("2027-03-15", "700", "SCL")] + [
        (f"2027-04-{d:02d}", "800", "EZE") for d in range(1, 10)
    ]
    months = calendar_months(calendar_snapshot(days))
    assert [m.title for m in months] == ["Marzo 2027", "Abril 2027"]
    cells = {c.day: c for m in months for w in m.weeks for c in w if c}
    assert cells[date(2027, 3, 15)].cheapest and cells[date(2027, 3, 15)].cheap
    assert not cells[date(2027, 3, 12)].cheap and cells[date(2027, 3, 12)].price == Decimal("900")
    assert cells[date(2027, 3, 11)].price is None  # no data for that day
    assert cells[date(2027, 3, 15)].origin == "SCL"
    assert "15 de marzo" in cells[date(2027, 3, 15)].aria_label
    assert sum(c.cheapest for c in cells.values()) == 1


def test_calendar_months_empty_without_calendar_mode():
    assert calendar_months(SNAPSHOT_A_B_C) == []


# -- month form --------------------------------------------------------------------------


def test_month_form_builds_a_calendar_query(settings_store):
    client, queries = recording_client(settings_store)
    assert client.get("/buscar/validar?" + MONTH_QS).status_code == 204
    _results(client, MONTH_QS)
    (query,) = queries
    assert query.calendar is True
    assert (query.depart_from, query.depart_to) == (date(2027, 3, 1), date(2027, 4, 30))
    assert query.origins == ("MDZ", "SCL") and (query.nights_min, query.nights_max) == (14, 21)


def test_month_form_without_end_month_uses_a_single_month(settings_store):
    client, queries = recording_client(settings_store)
    _results(client, MONTH_QS.replace("&hasta_mes=2027-04", ""))
    assert queries[0].depart_to == date(2027, 3, 31)


def test_month_form_validation_errors_are_spanish(client):
    past = MONTH_QS.replace("mes=2027-03", "mes=2020-01").replace("mes=2027-04", "mes=2020-02")
    r = client.get("/buscar/validar?" + past)
    assert r.status_code == 422 and "Ese mes ya pasó" in unescape(r.text)
    r = client.get("/buscar/validar?" + MONTH_QS.replace("mes=2027-03", "mes=marzo"))
    assert r.status_code == 422 and "Mes inválido" in unescape(r.text)
    r = client.get("/buscar/validar?" + MONTH_QS.replace("hasta_mes=2027-04", "hasta_mes=2027-09"))
    assert r.status_code == 422 and "hasta 4 meses" in unescape(r.text)


def test_dates_mode_does_not_ask_for_a_calendar(settings_store):
    client, queries = recording_client(settings_store)
    _results(client, QS + "&modo=fechas")
    assert queries[0].calendar is False


def test_index_offers_month_pills_and_both_modes(client):
    html = client.get("/").text
    assert 'name="modo"' in html and 'name="mes"' in html and 'name="hasta_mes"' in html
    assert "2026-11" in html and "Fechas exactas" in html and "arrow" in html
    assert "fonts.googleapis.com" in html


# -- calendar rendering ------------------------------------------------------------------


def test_calendar_renders_clickable_days_with_cheap_ones_marked(settings_store):
    snapshot = calendar_snapshot([("2027-03-12", "900", "MDZ"), ("2027-03-15", "700", "SCL")])
    client, _ = recording_client(settings_store, snapshot)
    html = unescape(_results(client, MONTH_QS))
    assert "Marzo 2027" in html and "precio orientativo (Skiplagged)" in html
    assert 'type="button"' in html and 'data-day="2027-03-15"' in html
    assert 'data-origin="SCL"' in html and "aria-label=" in html
    assert html.count("day cheap") == 1 and "cheapest" in html
    assert 'data-day="2027-03-11"' not in html  # days without data are not clickable


def test_calendar_without_data_says_not_available(settings_store):
    snapshot = calendar_snapshot([], note="Skiplagged no respondió")
    client, _ = recording_client(settings_store, snapshot)
    html = unescape(_results(client, MONTH_QS))
    assert "no disponible" in html and "Skiplagged no respondió" in html
    assert "data-day=" not in html and 'class="itinerary"' in html


def test_dates_mode_results_have_no_calendar(client):
    assert "precio orientativo" not in _results(client, QS)


def test_best_origin_card_is_marked(settings_store):
    snapshot = SNAPSHOT_A_B_C.model_copy(
        update={"best_per_origin": {i.origin: i for i in SNAPSHOT_A_B_C.itineraries}}
    )
    client, _ = recording_client(settings_store, snapshot)
    html = _results(client, QS)
    assert html.count("origin-card best") == 1
    assert html.index("origin-card best") < html.index("Vía Santiago") < html.index("Vía Ezeiza")

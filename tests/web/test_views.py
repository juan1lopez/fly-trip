from datetime import date
from decimal import Decimal

from flytrip.engine.search import SourceStatus
from flytrip.web.views import (
    format_duration,
    format_short_date,
    format_usd,
    price_breakdown,
    status_label,
)
from tests.factories import T, make_itinerary


def test_views_formatting():
    assert format_usd(Decimal("1021")) == "1.021 USD" and format_usd(Decimal("757.6")) == "758 USD"
    assert format_duration(800) == "13 h 20 min" and format_duration(45) == "45 min"
    assert format_short_date(date(2027, 3, 19)) == "19/03"


def test_price_breakdown():
    scl = make_itinerary(origin="SCL", price="758", transfer=T("80", "7"))
    assert price_breakdown(scl) == "758 + 80 traslado"
    assert price_breakdown(make_itinerary(origin="MDZ", price="934")) == "934"
    eze = make_itinerary(origin="EZE", price="1021")
    assert price_breakdown(eze) == "1.021 + traslado (sin configurar)"


def test_status_label():
    ok = SourceStatus(source="kiwi", state="ok", latency_ms=2300, count=15)
    assert status_label(ok) == "Kiwi: OK (15 en 2,3 s)"
    paused = SourceStatus(source="google", state="paused", detail="429")
    assert status_label(paused) == "Google Flights: en pausa — 429"
    pending = SourceStatus(source="google", state="pending")
    assert status_label(pending) == "Google Flights: esperando"
    assert status_label(SourceStatus(source="kiwi", state="running")) == "Kiwi: buscando…"

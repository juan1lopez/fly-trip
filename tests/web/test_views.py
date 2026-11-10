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
    partial = SourceStatus(source="kiwi", state="partial", detail="falló EZE: Kiwi respondió 500")
    assert status_label(partial) == "Kiwi: parcial — falló EZE: Kiwi respondió 500"
    pending = SourceStatus(source="google", state="pending")
    assert status_label(pending) == "Google Flights: esperando"
    assert status_label(SourceStatus(source="kiwi", state="running")) == "Kiwi: buscando…"


def test_baggage_label_covers_every_case():
    from flytrip.core.models import Baggage
    from flytrip.web.views import baggage_label

    assert baggage_label(None) == "desconocido"
    assert baggage_label(Baggage(personal_item=0, cabin_bag=0, checked_bag=0)) == (
        "sin equipaje incluido"
    )
    assert baggage_label(Baggage(personal_item=1, cabin_bag=None, checked_bag=1)) == (
        "mochila + valija"
    )
    assert baggage_label(Baggage(personal_item=1, cabin_bag=1, checked_bag=1)) == (
        "mochila + cabina + valija"
    )


def test_month_options_offer_the_next_12_months() -> None:
    from datetime import date

    from flytrip.web.views import month_options

    options = month_options(date(2026, 11, 9))
    assert len(options) == 12
    assert options[0] == ("2026-11", "Nov 2026")
    assert ("2027-07", "Jul 2027") in options
    assert options[-1][0] == "2027-10"

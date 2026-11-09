from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from fli.models import SortBy, TripType
from fli.search import SearchConnectionError, SearchHTTPError, SearchTimeoutError
from fli.search.flights import SearchParseError

from flytrip.sources import google_flights
from flytrip.sources.base import PauseRegistry, SourceRequest, run_safely
from flytrip.sources.google_flights import (
    GOOGLE_PRICE_IS_TOTAL,
    GoogleFlightsSource,
    build_filters,
    google_search_url,
    normalize_results,
)
from tests.factories import CLOCK, FETCHED
from tests.fakes import FakeFli, load_fli

PAIR = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 19),
    depart_to=date(2027, 3, 19),
    nights_min=16,
    nights_max=16,
    adults=1,
    allow_separate_tickets=True,
)
ONEWAY = SourceRequest(
    origin="EZE",
    destination="MAD",
    depart_from=date(2027, 3, 19),
    depart_to=date(2027, 3, 19),
    nights_min=None,
    nights_max=None,
    adults=1,
    allow_separate_tickets=True,
)


def verified_total_price(item) -> float:
    return item[-1].price if isinstance(item, tuple) else item.price


def test_build_filters_round_trip():
    f = build_filters(PAIR)
    assert f.trip_type == TripType.ROUND_TRIP and f.sort_by == SortBy.CHEAPEST
    assert [s.travel_date for s in f.flight_segments] == ["2027-03-19", "2027-04-04"]
    assert f.passenger_info.adults == 1


def test_build_filters_one_way():
    f = build_filters(ONEWAY)
    assert f.trip_type == TripType.ONE_WAY and len(f.flight_segments) == 1


def test_build_filters_rejects_windows_and_non_airports():
    with pytest.raises(ValueError, match="fechas exactas"):
        build_filters(replace(PAIR, depart_to=date(2027, 3, 20)))
    with pytest.raises(ValueError, match="no es un aeropuerto"):
        build_filters(replace(PAIR, destination="Madrid"))


def test_google_search_url():
    assert google_search_url("SCL", "MAD", date(2027, 3, 19), date(2027, 4, 4)) == (
        "https://www.google.com/travel/flights?q=Flights%20to%20MAD%20from%20SCL%20on%202027-03-19"
        "%20through%202027-04-04&curr=USD&hl=es"
    )
    assert google_search_url("EZE", "MAD", date(2027, 3, 7), None).endswith(
        "on%202027-03-07&curr=USD&hl=es"
    )


def test_normalize_synthetic_oneway():
    [it] = normalize_results(
        load_fli("synthetic_oneway.json"),
        origin="EZE",
        destination="MAD",
        adults=1,
        fetched_at=FETCHED,
    )
    assert it.price_usd == Decimal("650") and it.trip_type == "oneway"
    assert it.separate_tickets is False
    assert [(s.carrier_code, s.flight_number) for s in it.outbound.segments] == [("AR", "1132")]
    assert it.offers[0].source == "google" and it.baggage is None


def test_round_trip_price_comes_from_verified_element():
    [it] = normalize_results(
        load_fli("synthetic_rt.json"),
        origin="SCL",
        destination="MAD",
        adults=1,
        fetched_at=FETCHED,
    )
    assert it.price_usd == Decimal("980")
    assert it.trip_type == "return" and it.inbound is not None


def test_priceless_results_are_dropped():
    raw = load_fli("synthetic_oneway.json")
    raw[0] = raw[0].model_copy(update={"price": None})
    assert (
        normalize_results(raw, origin="EZE", destination="MAD", adults=1, fetched_at=FETCHED) == []
    )


@pytest.mark.parametrize(
    "name,origin,destination",
    [("madrid_scl_rt.json", "SCL", "MAD"), ("madrid_eze_oneway.json", "EZE", "MAD")],
)
def test_normalize_scenario_fixtures(name, origin, destination):
    items = normalize_results(
        load_fli(name), origin=origin, destination=destination, adults=1, fetched_at=FETCHED
    )
    assert items and all(it.price_usd > 0 for it in items)
    assert all(it.offers[0].booking_url.startswith("https://") for it in items)


@pytest.mark.parametrize("is_total,factor", [(True, 1), (False, 2)])
def test_adults_price_follows_total_constant(monkeypatch, is_total, factor):
    monkeypatch.setattr(google_flights, "GOOGLE_PRICE_IS_TOTAL", is_total)
    raw = load_fli("synthetic_rt.json")
    [it] = normalize_results(raw, origin="SCL", destination="MAD", adults=2, fetched_at=FETCHED)
    assert it.price_usd == Decimal(str(verified_total_price(raw[0]))) * factor


def test_round_trip_separate_tickets_true_if_any_part_is():
    out, back = load_fli("synthetic_rt.json")[0]
    raw = [(out, back.model_copy(update={"self_transfer": True}))]
    [it] = normalize_results(raw, origin="SCL", destination="MAD", adults=1, fetched_at=FETCHED)
    assert it.separate_tickets is True


def test_round_trip_separate_tickets_unknown_when_no_flags():
    out, back = load_fli("synthetic_rt.json")[0]
    raw = [
        (
            out.model_copy(update={"self_transfer": None}),
            back.model_copy(update={"self_transfer": None}),
        )
    ]
    [it] = normalize_results(raw, origin="SCL", destination="MAD", adults=1, fetched_at=FETCHED)
    assert it.separate_tickets is None


@pytest.mark.live
async def test_live_two_adults_price_is_total():
    from flytrip.sources.google_flights import RealFliClient

    one = await GoogleFlightsSource(RealFliClient()).search(PAIR)
    two = await GoogleFlightsSource(RealFliClient()).search(replace(PAIR, adults=2))
    assert one.itineraries and two.itineraries, "Google no devolvió resultados"
    ratio = two.itineraries[0].price_usd / one.itineraries[0].price_usd
    # If Google reports the total for 2 adults, it is about double the 1-adult price.
    # The source then keeps it as is (GOOGLE_PRICE_IS_TOTAL=True) and the ratio is ~2.
    assert (ratio > Decimal("1.8")) == GOOGLE_PRICE_IS_TOTAL


async def test_search_ok_counts_fetches_and_uses_fixed_params():
    fake = FakeFli(load_fli("synthetic_rt.json"))
    r = await GoogleFlightsSource(fake, clock=CLOCK).search(PAIR)
    assert r.status == "ok" and len(r.itineraries) == 1 and r.fetches == 2
    assert fake.calls[0][1] == {"top_n": 1, "currency": "USD", "language": "es", "country": "AR"}
    one = await GoogleFlightsSource(FakeFli(load_fli("synthetic_oneway.json")), clock=CLOCK).search(
        ONEWAY
    )
    assert one.fetches == 1


async def test_no_results_is_ok_and_empty():
    r = await GoogleFlightsSource(FakeFli(None), clock=CLOCK).search(PAIR)
    assert r.status == "ok" and r.itineraries == ()


async def test_wrong_currency_is_error():
    r = await GoogleFlightsSource(FakeFli(load_fli("wrong_currency.json")), clock=CLOCK).search(
        PAIR
    )
    assert r.status == "error" and "moneda inesperada" in r.detail and r.itineraries == ()


async def test_429_pauses_google(tmp_path):
    pauses = PauseRegistry(tmp_path / "p.json", CLOCK)
    src = GoogleFlightsSource(FakeFli(raises=SearchHTTPError("x", status_code=429)), clock=CLOCK)
    result = await run_safely(src, PAIR, timeout_s=5, pauses=pauses, clock=CLOCK)
    assert result.status == "paused"


@pytest.mark.parametrize(
    "exc,status,detail",
    [
        (SearchHTTPError("x", status_code=503), "error", "Google respondió 503"),
        (SearchTimeoutError("t"), "timeout", ""),
        (SearchConnectionError("c"), "error", "Sin conexión con Google Flights"),
        (SearchParseError("bad"), "error", "Google cambió el formato de la página"),
    ],
)
async def test_exceptions_are_mapped(exc, status, detail):
    r = await GoogleFlightsSource(FakeFli(raises=exc), clock=CLOCK).search(PAIR)
    assert r.status == status
    if detail:
        assert r.detail == detail

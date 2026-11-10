import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from fli.models import SortBy, TripType
from fli.search import SearchClientError, SearchConnectionError, SearchHTTPError, SearchTimeoutError
from fli.search.flights import SearchParseError

from flytrip.sources import google_flights
from flytrip.sources.base import PauseRegistry, SourceBlocked, SourceRequest, run_safely
from flytrip.sources.google_flights import (
    GOOGLE_PRICE_IS_TOTAL,
    GoogleFlightsSource,
    RealFliClient,
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


def test_recorded_fixtures_confirm_live_facts():
    one = load_fli("madrid_scl_rt.json")
    two = load_fli("madrid_scl_rt_2adults.json")
    # (a) USD respected; (c) datetimes naive; (b) the last tuple element is the pair's total.
    for pair in one:
        assert all(p.currency == "USD" for p in pair)
        assert all(leg.departure_datetime.tzinfo is None for p in pair for leg in p.legs)
        assert pair[-1].price is not None and pair[-1].price >= pair[0].price
    # (d) with 2 adults, Google's displayed price is already the total for both.
    assert two[0][-1].price == 2 * one[0][-1].price
    [first, *_] = normalize_results(
        two, origin="SCL", destination="MAD", adults=2, fetched_at=FETCHED
    )
    assert first.price_usd == Decimal(str(two[0][-1].price))


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
def test_live_two_adults_price_is_total():
    from flytrip.sources.google_flights import RealFliClient

    client = RealFliClient()
    kwargs = {"top_n": 1, "currency": "USD", "language": "es", "country": "AR"}
    raw1 = client.search(build_filters(PAIR), **kwargs)
    raw2 = client.search(build_filters(replace(PAIR, adults=2)), **kwargs)
    if not raw1 or not raw2:
        pytest.skip("Google no devolvió resultados (posible bloqueo); no se puede verificar")
    price1 = Decimal(str(verified_total_price(raw1[0])))
    price2 = Decimal(str(verified_total_price(raw2[0])))
    ratio = price2 / price1
    if abs(ratio - 2) <= Decimal("0.3"):
        observed_total = True
    elif abs(ratio - 1) <= Decimal("0.15"):
        observed_total = False
    else:
        pytest.fail(f"Relación de precios inesperada para 2 adultos: {ratio}")
    assert observed_total == GOOGLE_PRICE_IS_TOTAL


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


async def test_calls_queued_behind_a_429_never_reach_fli():
    fake = FakeFli(raises=SearchHTTPError("x", status_code=429))
    source = GoogleFlightsSource(fake, clock=CLOCK, max_concurrency=1)
    outcomes = await asyncio.gather(
        *(source.search(PAIR) for _ in range(4)), return_exceptions=True
    )
    assert len(fake.calls) == 1
    assert all(isinstance(o, SourceBlocked) for o in outcomes)
    assert "429" in outcomes[-1].reason


async def test_google_is_called_again_once_the_429_block_expires():
    moment = [datetime(2026, 11, 9, 15, 0, tzinfo=UTC)]
    fake = FakeFli(raises=SearchHTTPError("x", status_code=429))
    source = GoogleFlightsSource(fake, clock=lambda: moment[0])
    with pytest.raises(SourceBlocked):
        await source.search(PAIR)
    with pytest.raises(SourceBlocked):
        await source.search(PAIR)
    assert len(fake.calls) == 1
    moment[0] += timedelta(minutes=61)
    with pytest.raises(SourceBlocked):
        await source.search(PAIR)
    assert len(fake.calls) == 2


def test_real_fli_client_makes_one_http_request_per_fetch():
    class FailingSession:
        gets = 0

        def get(self, url, **kwargs):
            FailingSession.gets += 1
            raise RuntimeError("boom")

    client = RealFliClient()
    client._client._session = lambda: FailingSession()  # type: ignore[method-assign]
    with pytest.raises(SearchClientError):
        client.search(build_filters(ONEWAY), top_n=1, currency="USD", language="es", country="AR")
    assert FailingSession.gets == 1


def test_real_fli_client_does_not_refetch_a_page_without_payload():
    class EmptyPageSession:
        gets = 0

        def get(self, url, **kwargs):
            EmptyPageSession.gets += 1

            class Response:
                text = "<html>consent</html>"

                def raise_for_status(self):
                    return None

            return Response()

    client = RealFliClient()
    client._client._session = lambda: EmptyPageSession()  # type: ignore[method-assign]
    with pytest.raises(SearchParseError):
        client.search(build_filters(ONEWAY), top_n=1, currency="USD", language="es", country="AR")
    assert EmptyPageSession.gets == 1


def _synthetic_oneway_with(**leg_changes):
    [result] = load_fli("synthetic_oneway.json")[:1]
    leg = result.legs[0].model_copy(update=leg_changes)
    return result.model_copy(update={"legs": [leg]})


def _only(result):
    [it] = normalize_results(
        [result], origin="EZE", destination="MAD", adults=1, fetched_at=FETCHED
    )
    return it


def test_airline_codes_lose_fli_enum_underscore_and_flight_numbers_are_normalized():
    from fli.models import Airline

    it = _only(_synthetic_oneway_with(airline=Airline._2Z, flight_number="2Z 0045"))
    segment = it.outbound.segments[0]
    assert (segment.carrier_code, segment.flight_number) == ("2Z", "45")
    plain = _only(_synthetic_oneway_with(flight_number="AR 01132"))
    assert plain.outbound.segments[0].flight_number == "1132"


def test_same_flight_from_kiwi_and_google_gets_the_same_itinerary_id():
    from flytrip.core.legs import build_leg, itinerary_id, normalize_flight_number
    from flytrip.core.models import Segment

    google = _only(_synthetic_oneway_with(flight_number="AR 01132"))
    google_segment = google.outbound.segments[0]
    kiwi_segment = Segment(
        carrier_code="AR",
        carrier_name="Aerolíneas Argentinas",
        flight_number=normalize_flight_number("AR", "AR1132"),
        from_airport=google_segment.from_airport,
        to_airport=google_segment.to_airport,
        departure_local=google_segment.departure_local,
        arrival_local=google_segment.arrival_local,
    )
    kiwi_leg = build_leg([kiwi_segment], google.outbound.duration_minutes)
    assert itinerary_id(kiwi_leg, None) == google.id

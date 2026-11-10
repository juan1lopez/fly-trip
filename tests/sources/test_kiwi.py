from datetime import date
from decimal import Decimal

import httpx
import pytest
import respx

from flytrip.core.models import Baggage
from flytrip.sources.base import PauseRegistry, SourceRequest, run_safely
from flytrip.sources.kiwi import (
    KIWI_PRICE_IS_TOTAL,
    KIWI_URL,
    KiwiSource,
    build_arguments,
    build_rpc_body,
    normalize,
    parse_sse,
    split_window,
)
from tests.factories import CLOCK, FETCHED, fixture

REQ = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 1),
    depart_to=date(2027, 5, 31),
    nights_min=14,
    nights_max=21,
    adults=1,
    allow_separate_tickets=False,
)
SHORT_REQ = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 1),
    depart_to=date(2027, 3, 10),
    nights_min=14,
    nights_max=21,
    adults=1,
    allow_separate_tickets=False,
)


def test_build_arguments_return_trip():
    assert build_arguments(REQ) == {
        "flyFrom": "SCL",
        "flyTo": "MAD",
        "departureDate": "01/03/2027",
        "departureDateTo": "31/05/2027",
        "adults": 1,
        "currency": "USD",
        "locale": "es",
        "sort": "price",
        "allow_self_transfer": False,
        "nights_in_dst_from": 14,
        "nights_in_dst_to": 21,
    }


def test_build_arguments_oneway_has_no_nights():
    oneway = REQ.__class__(**{**REQ.__dict__, "nights_min": None, "nights_max": None})
    assert "nights_in_dst_from" not in build_arguments(oneway)


def test_build_rpc_body_calls_search_flight():
    body = build_rpc_body({"flyFrom": "SCL"}, request_id=7)
    assert body == {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "tools/call",
        "params": {"name": "search-flight", "arguments": {"flyFrom": "SCL"}},
    }


def test_split_window_92_days():
    assert split_window(date(2027, 1, 1), date(2027, 12, 31), 92) == [
        (date(2027, 1, 1), date(2027, 4, 2)),
        (date(2027, 4, 3), date(2027, 7, 3)),
        (date(2027, 7, 4), date(2027, 10, 3)),
        (date(2027, 10, 4), date(2027, 12, 31)),
    ]


def test_parse_sse_accepts_plain_json():
    assert parse_sse('{"jsonrpc": "2.0", "id": 1, "result": {}}')["result"] == {}


@pytest.mark.parametrize("name", ["synthetic_two_segments.sse", "synthetic_text_only.sse"])
def test_normalize_synthetic(name):
    [it] = normalize(parse_sse(fixture("kiwi", name)), origin="MDZ", adults=1, fetched_at=FETCHED)
    assert it.price_usd == Decimal("934")
    assert it.trip_type == "return"
    assert it.destination == "MAD"
    assert [(s.carrier_code, s.flight_number) for s in it.outbound.segments] == [
        ("JA", "7104"),
        ("IB", "6830"),
    ]
    assert it.outbound.layovers[0].minutes == 1010
    assert it.outbound.duration_minutes == 1830
    assert it.inbound is not None
    assert it.inbound.layovers[0].minutes == 315
    assert it.inbound.duration_minutes == 1125
    assert it.baggage == Baggage(personal_item=1, cabin_bag=1, checked_bag=0)
    assert it.offers[0].booking_url == "https://kiwi.com/u/abc123"
    assert it.separate_tickets is None


RECORDED_KIWI_FIXTURES = [
    ("madrid_scl_return.sse", "SCL"),
    ("madrid_mdz_return_all.sse", "MDZ"),
    ("madrid_mdz_return_protected.sse", "MDZ"),
    ("madrid_eze_return.sse", "EZE"),
]


@pytest.mark.parametrize("name,origin", RECORDED_KIWI_FIXTURES)
def test_recorded_fixtures_normalize(name, origin):
    rpc = parse_sse(fixture("kiwi", name))
    data = rpc["result"]["structuredContent"]
    itins = normalize(rpc, origin=origin, adults=1, fetched_at=FETCHED)
    assert len(itins) == data["resultsCount"]
    assert all(i.price_usd > 0 for i in itins)


def test_two_adults_price_is_total():
    rpc = parse_sse(fixture("kiwi", "madrid_scl_return_2adults.sse"))
    raw = Decimal(str(rpc["result"]["structuredContent"]["itineraries"][0]["price"]))
    [first, *_] = normalize(rpc, origin="SCL", adults=2, fetched_at=FETCHED)
    assert first.price_usd == (raw if KIWI_PRICE_IS_TOTAL else raw * 2)


@respx.mock
async def test_tool_error_and_wrong_currency_are_errors():
    respx.post(KIWI_URL).mock(
        side_effect=[
            httpx.Response(200, text=fixture("kiwi", "tool_error.sse")),
            httpx.Response(200, text=fixture("kiwi", "wrong_currency.sse")),
        ]
    )
    async with httpx.AsyncClient() as c:
        src = KiwiSource(c, clock=CLOCK)
        assert (await src.search(SHORT_REQ)).detail == "Kiwi: Invalid date"
        assert "moneda inesperada" in (await src.search(SHORT_REQ)).detail


@respx.mock
async def test_http_error_is_reported():
    respx.post(KIWI_URL).mock(return_value=httpx.Response(500))
    async with httpx.AsyncClient() as c:
        result = await KiwiSource(c, clock=CLOCK).search(SHORT_REQ)
    assert result.status == "error"
    assert result.detail == "Kiwi respondió 500"


@respx.mock
async def test_search_counts_one_fetch_per_window():
    route = respx.post(KIWI_URL).mock(
        return_value=httpx.Response(200, text=fixture("kiwi", "empty.sse"))
    )
    async with httpx.AsyncClient() as c:
        result = await KiwiSource(c, clock=CLOCK).search(SHORT_REQ)
    assert route.call_count == 1
    assert result.status == "ok" and result.fetches == 1 and result.itineraries == ()


@respx.mock
async def test_429_pauses_kiwi(tmp_path):
    respx.post(KIWI_URL).mock(return_value=httpx.Response(429))
    pauses = PauseRegistry(tmp_path / "p.json", CLOCK)
    async with httpx.AsyncClient() as c:
        r = await run_safely(
            KiwiSource(c, clock=CLOCK), SHORT_REQ, timeout_s=5, pauses=pauses, clock=CLOCK
        )
    assert r.status == "paused"
    assert pauses.active_pause("kiwi") is not None


@respx.mock
async def test_request_sends_identifying_headers():
    route = respx.post(KIWI_URL).mock(
        return_value=httpx.Response(200, text=fixture("kiwi", "empty.sse"))
    )
    async with httpx.AsyncClient() as c:
        await KiwiSource(c, clock=CLOCK).search(SHORT_REQ)
    headers = route.calls.last.request.headers
    assert headers["user-agent"] == "fly-trip/0.1 (uso personal)"
    assert headers["accept"] == "application/json, text/event-stream"

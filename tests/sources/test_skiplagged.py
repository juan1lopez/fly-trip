import asyncio
import json
from datetime import date, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from flytrip.sources.base import SourceBlocked, SourceRequest
from flytrip.sources.skiplagged import (
    SKIPLAGGED_HEADERS,
    SKIPLAGGED_MAX_CONCURRENCY,
    SKIPLAGGED_URL,
    CalendarResult,
    SkiplaggedProtocolError,
    SkiplaggedSource,
    SkiplaggedToolError,
    build_calendar_arguments,
    build_search_arguments,
    normalize_calendar,
    normalize_search,
    normalize_search_counted,
    parse_response,
)
from tests.factories import CLOCK, FETCHED, fixture

EXACT = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 19),
    depart_to=date(2027, 3, 19),
    nights_min=17,
    nights_max=17,
    adults=2,
    allow_separate_tickets=True,
)
ONEWAY = SourceRequest(
    origin="EZE",
    destination="MAD",
    depart_from=date(2027, 3, 9),
    depart_to=date(2027, 3, 9),
    nights_min=None,
    nights_max=None,
    adults=1,
    allow_separate_tickets=False,
)


def _normalize(name: str, adults: int = 2):
    return normalize_search(
        parse_response(fixture("skiplagged", name)),
        origin="SCL",
        adults=adults,
        fetched_at=FETCHED,
    )


def test_constants():
    assert SKIPLAGGED_URL == "https://mcp.skiplagged.com/mcp"
    assert SKIPLAGGED_MAX_CONCURRENCY == 2
    assert SKIPLAGGED_HEADERS["User-Agent"] == "fly-trip/0.1 (uso personal)"
    assert SKIPLAGGED_HEADERS["Accept"] == "application/json, text/event-stream"


def test_search_arguments_return_trip():
    assert build_search_arguments(EXACT) == {
        "origin": "SCL",
        "destination": "MAD",
        "departureDate": "2027-03-19",
        "returnDate": "2027-04-05",
        "currency": "USD",
        "adults": 2,
        "sort": "price",
        "limit": 20,
        "includeHiddenCity": False,
        "includeVirtualInterlining": True,
    }


def test_search_arguments_oneway_and_no_separate_tickets():
    arguments = build_search_arguments(ONEWAY)
    assert "returnDate" not in arguments
    assert arguments["includeVirtualInterlining"] is False
    assert arguments["includeHiddenCity"] is False


def test_hidden_city_is_never_requested():
    for request in (EXACT, ONEWAY):
        assert build_search_arguments(request)["includeHiddenCity"] is False


def test_search_arguments_reject_ranges():
    ranged = SourceRequest(**{**EXACT.__dict__, "depart_to": date(2027, 3, 25)})
    with pytest.raises(ValueError, match="Skiplagged solo confirma fechas exactas"):
        build_search_arguments(ranged)
    nights = SourceRequest(**{**EXACT.__dict__, "nights_max": 21})
    with pytest.raises(ValueError, match="Skiplagged solo confirma fechas exactas"):
        build_search_arguments(nights)


def test_calendar_arguments():
    assert build_calendar_arguments("EZE", "MAD", date(2027, 3, 15), date(2027, 3, 29)) == {
        "origin": "EZE",
        "destination": "MAD",
        "departureDate": "2027-03-15",
        "returnDate": "2027-03-29",
        "currency": "USD",
    }
    assert "returnDate" not in build_calendar_arguments("EZE", "MAD", date(2027, 3, 15), None)


def test_normalize_synthetic_exact():
    items = _normalize("synthetic_rt.sse")
    assert [i.offers[0].price_usd for i in items] == [
        Decimal("1430"),
        Decimal("2056"),
        Decimal("1768"),
    ]
    direct, virtual, unknown = items
    assert [i.separate_tickets for i in items] == [False, True, None]
    assert direct.origin == "SCL" and direct.destination == "MAD"
    assert direct.trip_type == "return"
    assert direct.baggage is None
    seg = direct.outbound.segments[0]
    assert (seg.carrier_code, seg.flight_number) == ("IB", "114")
    assert (seg.from_airport, seg.to_airport) == ("SCL", "MAD")
    # The offset is dropped: local wall-clock times.
    assert seg.departure_local == datetime(2027, 3, 19, 0, 50)
    assert seg.arrival_local == datetime(2027, 3, 19, 17, 30)
    assert direct.outbound.duration_minutes == 12 * 60 + 40
    assert direct.outbound.stops == 0
    back = direct.inbound
    assert back is not None
    assert [(s.carrier_code, s.flight_number) for s in back.segments] == [
        ("IB", "269"),
        ("LA", "777"),
    ]
    assert back.segments[1].arrival_local == datetime(2027, 4, 4, 22, 50)
    assert back.duration_minutes == 16 * 60 + 35
    assert back.stops == 1 and back.layovers[0].airport == "GIG" and back.layovers[0].minutes == 95
    offer = direct.offers[0]
    assert offer.source == "skiplagged"
    assert offer.fetched_at == FETCHED
    assert offer.booking_url == (
        "https://skiplagged.com/flights/SCL/MAD/2027-03-19/2027-04-04"
        "?utm_source=mcp&utm_medium=ai&utm_campaign=skiplagged_mcp#trip=IB114,IB269-LA777"
    )
    # Virtual interlining with an airport change (GRU -> VCP) and three segments.
    assert virtual.outbound.stops == 2
    assert virtual.outbound.layovers[0].airport_change is True
    assert virtual.outbound.duration_minutes == 24 * 60 + 25
    assert [s.flight_number for s in virtual.outbound.segments] == ["750", "8752", "9441"]
    assert len({i.id for i in items}) == 3


def test_price_is_the_total_for_the_group():
    # Verified live: 715 USD for 1 adult became 1430 for 2 adults. No multiplication.
    items = _normalize("synthetic_rt.sse", adults=2)
    assert items[0].offers[0].price_usd == Decimal("1430")


def test_hidden_city_items_are_discarded():
    items = _normalize("hidden_city.sse")
    assert [i.offers[0].price_usd for i in items] == [Decimal("1430")]
    assert all("AV240" not in i.offers[0].booking_url for i in items)


def test_non_https_links_are_dropped():
    rpc = parse_response(fixture("skiplagged", "synthetic_rt.sse"))
    flights = rpc["result"]["structuredContent"]["flights"]
    flights[0]["deepLink"] = flights[0]["deepLink"].replace("https://", "http://")
    items = normalize_search(rpc, origin="SCL", adults=2, fetched_at=FETCHED)
    assert len(items) == 2


def test_empty_response_is_not_an_error():
    assert _normalize("empty.sse") == []


def test_tool_error_and_malformed():
    with pytest.raises(SkiplaggedToolError, match="Invalid airport code"):
        _normalize("tool_error.sse")
    with pytest.raises(SkiplaggedProtocolError):
        parse_response(fixture("skiplagged", "malformed.sse"))


def test_wrong_currency_is_a_protocol_error():
    rpc = parse_response(fixture("skiplagged", "synthetic_rt.sse"))
    rpc["result"]["structuredContent"]["pricing"]["currency"] = "ARS"
    with pytest.raises(SkiplaggedProtocolError, match="moneda"):
        normalize_search(rpc, origin="SCL", adults=2, fetched_at=FETCHED)


def test_recorded_search_normalizes():
    items = _normalize("madrid_scl_rt.sse", adults=1)
    assert len(items) == 5
    assert min(i.offers[0].price_usd for i in items) == Decimal("715")
    assert all(i.separate_tickets is False for i in items)
    assert all(i.inbound is not None for i in items)
    assert items[0].outbound.segments[0].departure_local == datetime(2027, 3, 19, 0, 50)


def test_recorded_calendar_normalizes():
    days = normalize_calendar(parse_response(fixture("skiplagged", "calendar_eze_mad.sse")))
    assert days[0] == (date(2027, 2, 13), Decimal("1281"))
    assert (date(2027, 3, 15), Decimal("1211")) in days
    assert len(days) > 40
    assert len({d for d, _ in days}) == len(days)


def test_calendar_tool_error():
    with pytest.raises(SkiplaggedToolError):
        normalize_calendar(parse_response(fixture("skiplagged", "tool_error.sse")))


def _source(client: httpx.AsyncClient, **kwargs) -> SkiplaggedSource:
    kwargs.setdefault("min_interval_s", 0)  # pacing has its own tests
    return SkiplaggedSource(client, clock=CLOCK, **kwargs)


@respx.mock
async def test_search_sends_rpc_with_headers():
    route = respx.post(SKIPLAGGED_URL).mock(
        return_value=httpx.Response(200, text=fixture("skiplagged", "synthetic_rt.sse"))
    )
    async with httpx.AsyncClient() as client:
        result = await _source(client).search(EXACT)
    assert result.status == "ok" and len(result.itineraries) == 3 and result.fetches == 1
    sent = route.calls[0].request
    assert sent.headers["user-agent"] == "fly-trip/0.1 (uso personal)"
    assert sent.headers["accept"] == "application/json, text/event-stream"
    body = json.loads(sent.content)
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "sk_flights_search"
    assert body["params"]["arguments"] == build_search_arguments(EXACT)


@respx.mock
async def test_search_tool_error_malformed_and_http_error():
    cases = [
        (httpx.Response(200, text=fixture("skiplagged", "tool_error.sse")), "Invalid airport"),
        (httpx.Response(200, text=fixture("skiplagged", "malformed.sse")), "Skiplagged"),
        (httpx.Response(500, text="boom"), "500"),
    ]
    for response, expected in cases:
        respx.post(SKIPLAGGED_URL).mock(return_value=response)
        async with httpx.AsyncClient() as client:
            result = await _source(client).search(EXACT)
        assert result.status == "error"
        assert expected in result.detail


@respx.mock
async def test_search_transport_error_and_timeout():
    respx.post(SKIPLAGGED_URL).mock(side_effect=httpx.ConnectError("down"))
    async with httpx.AsyncClient() as client:
        assert (await _source(client).search(EXACT)).status == "error"
    respx.post(SKIPLAGGED_URL).mock(side_effect=httpx.ReadTimeout("slow"))
    async with httpx.AsyncClient() as client:
        assert (await _source(client).search(EXACT)).status == "timeout"


@respx.mock
async def test_429_blocks_and_queued_calls_never_reach_the_server():
    route = respx.post(SKIPLAGGED_URL).mock(return_value=httpx.Response(429))
    async with httpx.AsyncClient() as client:
        source = _source(client, max_concurrency=1)
        first, second = await asyncio.gather(
            source.search(EXACT), source.search(EXACT), return_exceptions=True
        )
        assert isinstance(first, SourceBlocked) and isinstance(second, SourceBlocked)
        assert route.call_count == 1
        with pytest.raises(SourceBlocked):
            await source.search(EXACT)
        assert route.call_count == 1


@respx.mock
async def test_calendar_ok():
    route = respx.post(SKIPLAGGED_URL).mock(
        return_value=httpx.Response(200, text=fixture("skiplagged", "calendar_eze_mad.sse"))
    )
    async with httpx.AsyncClient() as client:
        result = await _source(client).calendar("EZE", "MAD", date(2027, 3, 15), date(2027, 3, 29))
    assert isinstance(result, CalendarResult)
    assert result.source == "skiplagged" and result.status == "ok"
    assert result.days[0] == (date(2027, 2, 13), Decimal("1281"))
    body = json.loads(route.calls[0].request.content)
    assert body["params"]["name"] == "sk_flex_departure_calendar"
    assert body["params"]["arguments"]["returnDate"] == "2027-03-29"


@respx.mock
async def test_calendar_never_raises():
    cases = [
        (httpx.Response(200, text=fixture("skiplagged", "tool_error.sse")), "error"),
        (httpx.Response(200, text=fixture("skiplagged", "malformed.sse")), "error"),
        (httpx.Response(503), "error"),
        (httpx.ConnectError("down"), "error"),
        (httpx.ReadTimeout("slow"), "timeout"),
    ]
    for outcome, status in cases:
        if isinstance(outcome, Exception):
            respx.post(SKIPLAGGED_URL).mock(side_effect=outcome)
        else:
            respx.post(SKIPLAGGED_URL).mock(return_value=outcome)
        async with httpx.AsyncClient() as client:
            result = await _source(client).calendar("EZE", "MAD", date(2027, 3, 15), None)
        assert result.status == status
        assert result.days == ()
        assert result.detail


@respx.mock
async def test_calendar_429_pauses_and_blocks_search_too():
    route = respx.post(SKIPLAGGED_URL).mock(return_value=httpx.Response(429))
    async with httpx.AsyncClient() as client:
        source = _source(client)
        result = await source.calendar("EZE", "MAD", date(2027, 3, 15), None)
        assert result.status == "paused"
        again = await source.calendar("EZE", "MAD", date(2027, 3, 15), None)
        assert again.status == "paused"
        with pytest.raises(SourceBlocked):
            await source.search(EXACT)
    assert route.call_count == 1


def _synthetic_rpc():
    return parse_response(fixture("skiplagged", "synthetic_rt.sse"))


def test_card_ending_elsewhere_is_dropped_without_any_flag():
    rpc = _synthetic_rpc()
    text = rpc["result"]["content"][0]["text"]
    rpc["result"]["content"][0]["text"] = text.replace(
        "SCL → MAD (2027-03-19 00:50:00-03:00", "SCL → BCN (2027-03-19 00:50:00-03:00"
    )
    kwargs = {"origin": "SCL", "adults": 2, "fetched_at": FETCHED}
    kept = normalize_search(rpc, destination="MAD", **kwargs)
    assert [i.offers[0].price_usd for i in kept] == [Decimal("2056"), Decimal("1768")]
    # Without the optional destination, the card/row cross-check still applies.
    with pytest.raises(SkiplaggedProtocolError):
        normalize_search(rpc, **kwargs)


def test_row_must_match_the_structured_card():
    rpc = _synthetic_rpc()
    card = rpc["result"]["structuredContent"]["flights"][0]
    card["arrival"]["dateTime"] = "2027-03-19T18:30:00+01:00"
    with pytest.raises(SkiplaggedProtocolError, match="no coincide"):
        normalize_search(rpc, origin="SCL", adults=2, fetched_at=FETCHED)
    rpc = _synthetic_rpc()
    card = rpc["result"]["structuredContent"]["flights"][0]
    card["returnFlight"]["departure"]["dateTime"] = "2027-04-04T13:15:00+02:00"
    with pytest.raises(SkiplaggedProtocolError, match="no coincide"):
        normalize_search(rpc, origin="SCL", adults=2, fetched_at=FETCHED)


def test_trip_shape_must_match_the_request():
    rpc = _synthetic_rpc()
    kwargs = {"origin": "SCL", "adults": 2, "fetched_at": FETCHED}
    assert normalize_search(rpc, round_trip=False, **kwargs) == []
    assert len(normalize_search(rpc, round_trip=True, **kwargs)) == 3


@respx.mock
async def test_unexpected_parse_errors_become_formato_cambiado():
    rpc = _synthetic_rpc()
    rpc["result"]["structuredContent"]["flights"][0]["price"]["amount"] = "abc"
    sse = "data: " + json.dumps(rpc) + "\n\n"
    respx.post(SKIPLAGGED_URL).mock(return_value=httpx.Response(200, text=sse))
    async with httpx.AsyncClient() as client:
        result = await _source(client).search(EXACT)
    assert result.status == "error"
    assert result.detail == "Skiplagged: formato cambiado"


async def test_queueing_behind_the_semaphore_does_not_count_toward_the_timeout():
    active = 0
    peak = 0

    async def slow(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.1)
        active -= 1
        return httpx.Response(200, text=fixture("skiplagged", "calendar_eze_mad.sse"))

    client = httpx.AsyncClient(transport=httpx.MockTransport(slow))
    source = SkiplaggedSource(client, max_concurrency=3, request_timeout_s=0.25, min_interval_s=0)
    # 9 calls in 3 waves of 0.1 s: the last wave waits 0.2 s queued, then runs 0.1 s.
    results = await asyncio.gather(
        *(source.calendar("EZE", "MAD", date(2027, 3, 15), None) for _ in range(9))
    )
    assert peak == 3
    assert [r.status for r in results] == ["ok"] * 9


async def test_a_call_slower_than_the_request_timeout_times_out():
    async def stuck(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(5)
        return httpx.Response(200)

    source = SkiplaggedSource(
        httpx.AsyncClient(transport=httpx.MockTransport(stuck)),
        request_timeout_s=0.05,
        min_interval_s=0,
    )
    result = await source.calendar("EZE", "MAD", date(2027, 3, 15), None)
    assert result.status == "timeout"


class FakeTime:
    """An injected monotonic clock whose sleep just moves it forward."""

    def __init__(self) -> None:
        self.now = 1000.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def _paced(handler, fake: FakeTime, **kwargs) -> SkiplaggedSource:
    return SkiplaggedSource(
        httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=CLOCK,
        monotonic=fake.monotonic,
        sleep=fake.sleep,
        **kwargs,
    )


async def _ok_calendar(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, text=fixture("skiplagged", "calendar_eze_mad.sse"))


async def test_calls_start_at_least_one_second_apart():
    fake = FakeTime()
    starts: list[float] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        starts.append(fake.now)
        return await _ok_calendar(request)

    source = _paced(handler, fake)
    results = await asyncio.gather(
        *(source.calendar("EZE", "MAD", date(2027, 3, 15), None) for _ in range(4))
    )
    assert [r.status for r in results] == ["ok"] * 4
    assert all(b - a >= 1.0 for a, b in zip(starts, starts[1:], strict=False))
    assert starts[-1] - starts[0] >= 3.0


async def test_rolling_cap_skips_calls_beyond_30_in_10_minutes():
    fake = FakeTime()
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return await _ok_calendar(request)

    source = _paced(handler, fake, min_interval_s=0)
    results = [await source.calendar("EZE", "MAD", date(2027, 3, 15), None) for _ in range(31)]
    assert [r.status for r in results[:30]] == ["ok"] * 30
    assert results[30].status == "error" and "30 consultas" in results[30].detail
    assert calls == 30
    fake.now += 601  # the window rolls
    again = await source.calendar("EZE", "MAD", date(2027, 3, 15), None)
    assert again.status == "ok" and calls == 31


async def test_search_over_the_cap_is_an_error_result_not_a_block():
    fake = FakeTime()

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=fixture("skiplagged", "empty.sse"))

    source = _paced(handler, fake, min_interval_s=0, window_calls=1)
    assert (await source.search(EXACT)).status == "ok"
    capped = await source.search(EXACT)
    assert capped.status == "error" and "consultas" in capped.detail


async def test_429_with_a_long_retry_after_extends_the_pause():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": str(3 * 3600)})

    source = _paced(handler, FakeTime())
    with pytest.raises(SourceBlocked) as info:
        await source.search(EXACT)
    assert info.value.pause_minutes == 180
    result = await source.calendar("EZE", "MAD", date(2027, 3, 15), None)
    assert result.status == "paused" and result.pause_minutes == 180


async def test_429_with_a_short_or_missing_retry_after_keeps_the_hour():
    async def short(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "30"})

    with pytest.raises(SourceBlocked) as info:
        await _paced(short, FakeTime()).search(EXACT)
    assert info.value.pause_minutes == 60


async def test_search_reports_raw_and_dropped_counts():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=fixture("skiplagged", "hidden_city.sse"))

    result = await _paced(handler, FakeTime(), min_interval_s=0).search(EXACT)
    assert result.raw_count is not None and result.raw_count > len(result.itineraries)
    assert result.dropped >= 1


def test_zero_or_negative_prices_are_dropped():
    rpc = parse_response(fixture("skiplagged", "synthetic_rt.sse"))
    flights = rpc["result"]["structuredContent"]["flights"]
    before = len(normalize_search(rpc, origin="SCL", adults=2, fetched_at=FETCHED))
    flights[0]["price"]["amount"] = 0
    items, raw, dropped = normalize_search_counted(rpc, origin="SCL", adults=2, fetched_at=FETCHED)
    assert len(items) == before - 1 and dropped >= 1 and raw == len(flights)

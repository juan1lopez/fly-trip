import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx

from flytrip.core.legs import build_leg, itinerary_id, normalize_flight_number
from flytrip.core.models import Itinerary, Leg, Offer, Segment
from flytrip.sources.base import BLOCK_PAUSE_MINUTES, SourceBlocked, SourceRequest, SourceResult
from flytrip.sources.kiwi import KiwiProtocolError, parse_sse, utc_now

logger = logging.getLogger(__name__)

SKIPLAGGED_URL = "https://mcp.skiplagged.com/mcp"
SKIPLAGGED_MAX_CONCURRENCY = 3
SKIPLAGGED_SEARCH_LIMIT = 20
# Con adults=2 el precio ya es el total del grupo (ver docs/sources/skiplagged.md).
SKIPLAGGED_PRICE_IS_TOTAL = True
SKIPLAGGED_RATE_LIMITED = "Skiplagged limitó las consultas (429)"

SKIPLAGGED_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "User-Agent": "fly-trip/0.1 (uso personal)",
}

_SEGMENT = re.compile(r"([A-Z]{3}) → ([A-Z]{3}) \((\S+ \S+) → (\S+ \S+)\)")
_FLIGHT_CODE = re.compile(r"^([A-Z0-9]{2})(\d+)$")


class SkiplaggedToolError(Exception):
    pass


class SkiplaggedProtocolError(Exception):
    pass


@dataclass(frozen=True)
class CalendarResult:
    source: str
    status: Literal["ok", "paused", "error", "timeout"]
    days: tuple[tuple[date, Decimal], ...] = ()
    detail: str = ""
    latency_ms: int = 0


def build_search_arguments(request: SourceRequest) -> dict[str, object]:
    if request.depart_from != request.depart_to or request.nights_min != request.nights_max:
        raise ValueError("Skiplagged solo confirma fechas exactas")
    arguments: dict[str, object] = {
        "origin": request.origin,
        "destination": request.destination,
        "departureDate": request.depart_from.isoformat(),
    }
    if request.nights_min is not None:
        back = request.depart_from + timedelta(days=request.nights_min)
        arguments["returnDate"] = back.isoformat()
    arguments.update(
        {
            "currency": "USD",
            "adults": request.adults,
            "sort": "price",
            "limit": SKIPLAGGED_SEARCH_LIMIT,
            # Hidden city is never requested, and normalize_search also drops it.
            "includeHiddenCity": False,
            "includeVirtualInterlining": request.allow_separate_tickets,
        }
    )
    return arguments


def build_calendar_arguments(
    origin: str, destination: str, anchor: date, return_date: date | None
) -> dict[str, object]:
    arguments: dict[str, object] = {
        "origin": origin,
        "destination": destination,
        "departureDate": anchor.isoformat(),
    }
    if return_date is not None:
        arguments["returnDate"] = return_date.isoformat()
    arguments["currency"] = "USD"
    return arguments


def _rpc_body(tool: str, arguments: dict[str, object]) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


def parse_response(text: str) -> dict[str, Any]:
    try:
        return parse_sse(text)
    except KiwiProtocolError as exc:
        raise SkiplaggedProtocolError(str(exc)) from exc


def _structured(rpc: dict[str, Any]) -> dict[str, Any]:
    if rpc.get("error") is not None:
        error = rpc["error"]
        message = error.get("message") if isinstance(error, dict) else error
        raise SkiplaggedToolError(str(message))
    result = rpc.get("result")
    if not isinstance(result, dict):
        raise SkiplaggedProtocolError("respuesta sin resultado")
    if result.get("isError"):
        content = result.get("content") or [{}]
        raise SkiplaggedToolError(str(content[0].get("text") or "error desconocido"))
    data = result.get("structuredContent")
    if not isinstance(data, dict):
        raise SkiplaggedProtocolError("respuesta sin datos")
    return data


def _text(rpc: dict[str, Any]) -> str:
    content = rpc["result"].get("content") or [{}]
    return str(content[0].get("text", ""))


def _aware(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise SkiplaggedProtocolError("horario sin zona horaria")
    return parsed


def _parse_leg(part: str, codes: list[str]) -> Leg:
    matches = _SEGMENT.findall(part)
    if not matches or len(matches) != len(codes):
        raise SkiplaggedProtocolError("los tramos no coinciden con los vuelos")
    segments: list[Segment] = []
    first_departure: datetime | None = None
    last_arrival: datetime | None = None
    for (frm, to, dep, arr), code in zip(matches, codes, strict=True):
        flight = _FLIGHT_CODE.match(code)
        if flight is None:
            raise SkiplaggedProtocolError(f"vuelo ilegible: {code}")
        carrier, number = flight.groups()
        departure, arrival = _aware(dep), _aware(arr)
        first_departure = first_departure or departure
        last_arrival = arrival
        segments.append(
            Segment(
                carrier_code=carrier,
                carrier_name=carrier,
                flight_number=normalize_flight_number(carrier, number),
                from_airport=frm,
                to_airport=to,
                departure_local=departure.replace(tzinfo=None),
                arrival_local=arrival.replace(tzinfo=None),
            )
        )
    assert first_departure is not None and last_arrival is not None
    minutes = int((last_arrival - first_departure).total_seconds() // 60)
    return build_leg(segments, minutes)


def _rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        for link in re.findall(r"\((https://[^)\s]+)\)", line):
            rows[link] = line
    return rows


def _attributes(raw: dict[str, Any]) -> list[str]:
    attributes = [str(a) for a in raw.get("attributes") or []]
    back = raw.get("returnFlight")
    if isinstance(back, dict):
        attributes += [str(a) for a in back.get("attributes") or []]
    return attributes


def _is_hidden_city(raw: dict[str, Any], row: str | None) -> bool:
    flagged = any("hidden" in attribute.lower() for attribute in _attributes(raw))
    return flagged or (row is not None and "hidden city" in row.lower())


def _separate_tickets(raw: dict[str, Any]) -> bool | None:
    back = raw.get("returnFlight")
    legs = [raw.get("attributes") or []]
    if isinstance(back, dict):
        legs.append(back.get("attributes") or [])
    if any("virtual" in str(a) for leg in legs for a in leg):
        return True
    if all("standard" in leg for leg in legs):
        return False
    return None


def _card_time(card: Any, key: str) -> datetime:
    try:
        return _aware(str(card[key]["dateTime"])).replace(tzinfo=None)
    except (KeyError, TypeError) as exc:
        raise SkiplaggedProtocolError("tarjeta sin horarios") from exc


def _check_leg(leg: Leg, card: Any) -> None:
    """The row parsed from the text must agree with the structured card."""
    if (
        leg.segments[0].departure_local != _card_time(card, "departure")
        or leg.segments[-1].arrival_local != _card_time(card, "arrival")
        or leg.segments[0].from_airport != str(card["departure"].get("airport"))
        or leg.segments[-1].to_airport != str(card["arrival"].get("airport"))
    ):
        raise SkiplaggedProtocolError("el detalle de tramos no coincide con la tarjeta")


def normalize_search(
    rpc: dict[str, Any],
    *,
    origin: str,
    adults: int,
    fetched_at: datetime,
    destination: str | None = None,
    round_trip: bool | None = None,
) -> list[Itinerary]:
    data = _structured(rpc)
    pricing = data.get("pricing")
    currency = pricing.get("currency") if isinstance(pricing, dict) else None
    if currency != "USD":
        raise SkiplaggedProtocolError(f"moneda inesperada: {currency}")
    rows = _rows(_text(rpc))
    itineraries: list[Itinerary] = []
    dropped = 0
    for raw in data.get("flights") or []:
        link = str(raw.get("deepLink") or "")
        if _is_hidden_city(raw, rows.get(link)):
            continue
        if not link.startswith("https://") or "#trip=" not in link:
            continue
        row = rows.get(link)
        if row is None:
            raise SkiplaggedProtocolError("resultado sin detalle de tramos")
        price_raw = raw.get("price")
        if not isinstance(price_raw, dict) or price_raw.get("currency") != "USD":
            raise SkiplaggedProtocolError("precio inesperado")
        price = Decimal(str(price_raw["amount"]))
        if not SKIPLAGGED_PRICE_IS_TOTAL:
            price *= adults
        leg_codes = [leg.split("-") for leg in link.split("#trip=", 1)[1].split(",")]
        if round_trip is not None and (len(leg_codes) > 1) != round_trip:
            dropped += 1
            continue
        out_part, _, back_part = row.partition("Return:<br/>")
        outbound = _parse_leg(out_part, leg_codes[0])
        # Structural hidden-city defense: the trip must end where we asked to go.
        if destination is not None and outbound.segments[-1].to_airport != destination:
            dropped += 1
            continue
        _check_leg(outbound, raw)
        inbound = _parse_leg(back_part, leg_codes[1]) if len(leg_codes) > 1 else None
        if inbound is not None:
            back_card = raw.get("returnFlight")
            if not isinstance(back_card, dict):
                raise SkiplaggedProtocolError("tarjeta sin vuelta")
            _check_leg(inbound, back_card)
        itineraries.append(
            Itinerary(
                id=itinerary_id(outbound, inbound),
                origin=origin,
                destination=outbound.segments[-1].to_airport,
                trip_type="return" if inbound is not None else "oneway",
                outbound=outbound,
                inbound=inbound,
                offers=(
                    Offer(
                        source="skiplagged",
                        price_usd=price,
                        booking_url=link,
                        fetched_at=fetched_at,
                    ),
                ),
                baggage=None,
                separate_tickets=_separate_tickets(raw),
            )
        )
    if dropped:
        logger.debug("Skiplagged: %d tarjetas descartadas", dropped)
    return itineraries


def normalize_calendar(rpc: dict[str, Any]) -> list[tuple[date, Decimal]]:
    data = _structured(rpc)
    chart = data.get("chart")
    if not isinstance(chart, dict):
        raise SkiplaggedProtocolError("calendario sin datos")
    if chart.get("currency") != "USD":
        raise SkiplaggedProtocolError(f"moneda inesperada: {chart.get('currency')}")
    best: dict[date, Decimal] = {}
    for point in chart.get("points") or []:
        try:
            day = date.fromisoformat(str(point["departure"]))
            price = Decimal(str(point["price"]))
        except (KeyError, ValueError, ArithmeticError) as exc:
            raise SkiplaggedProtocolError("punto de calendario ilegible") from exc
        if price > 0 and (day not in best or price < best[day]):
            best[day] = price
    return sorted(best.items())


class SkiplaggedSource:
    name = "skiplagged"

    def __init__(
        self,
        client: httpx.AsyncClient,
        url: str = SKIPLAGGED_URL,
        clock: Callable[[], datetime] = utc_now,
        max_concurrency: int = SKIPLAGGED_MAX_CONCURRENCY,
    ) -> None:
        self._client = client
        self._url = url
        self._clock = clock
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._blocked_until: datetime | None = None

    async def aclose(self) -> None:
        await self._client.aclose()

    def _is_blocked(self) -> bool:
        return self._blocked_until is not None and self._clock() < self._blocked_until

    def _block(self) -> None:
        self._blocked_until = self._clock() + timedelta(minutes=BLOCK_PAUSE_MINUTES)

    async def _call(self, tool: str, arguments: dict[str, object]) -> dict[str, Any]:
        """One POST. Raises SourceBlocked on 429, httpx errors, and the protocol/tool errors."""
        async with self._semaphore:
            # Calls queued behind a 429 already passed the engine's pause check.
            if self._is_blocked():
                raise SourceBlocked(SKIPLAGGED_RATE_LIMITED)
            response = await self._client.post(
                self._url, json=_rpc_body(tool, arguments), headers=SKIPLAGGED_HEADERS
            )
        if response.status_code == 429:
            self._block()
            raise SourceBlocked(SKIPLAGGED_RATE_LIMITED)
        if response.status_code >= 400:
            raise SkiplaggedProtocolError(f"respondió {response.status_code}")
        return parse_response(response.text)

    @staticmethod
    def _failure(exc: Exception) -> tuple[str, str]:
        if isinstance(exc, httpx.TimeoutException):
            return "timeout", "Skiplagged no respondió a tiempo"
        if isinstance(exc, httpx.TransportError):
            return "error", f"Skiplagged no respondió ({type(exc).__name__})"
        return "error", f"Skiplagged: {exc}"

    async def search(self, request: SourceRequest) -> SourceResult:
        arguments = build_search_arguments(request)
        try:
            rpc = await self._call("sk_flights_search", arguments)
            try:
                itineraries = normalize_search(
                    rpc,
                    origin=request.origin,
                    adults=request.adults,
                    fetched_at=self._clock(),
                    destination=request.destination,
                    round_trip=request.nights_min is not None,
                )
            except (
                ValueError,
                KeyError,
                IndexError,
                ArithmeticError,
                TypeError,
                AttributeError,
            ) as exc:  # pydantic's ValidationError is a ValueError
                raise SkiplaggedProtocolError("formato cambiado") from exc
        except (httpx.TransportError, SkiplaggedToolError, SkiplaggedProtocolError) as exc:
            status, detail = self._failure(exc)
            return SourceResult(
                source=self.name,
                status=status,  # type: ignore[arg-type]
                detail=detail,
                fetches=1,
            )
        return SourceResult(
            source=self.name, status="ok", itineraries=tuple(itineraries), fetches=1
        )

    async def calendar(
        self, origin: str, destination: str, anchor: date, return_date: date | None
    ) -> CalendarResult:
        started = time.monotonic()

        def result(
            status: str, detail: str = "", days: tuple[tuple[date, Decimal], ...] = ()
        ) -> CalendarResult:
            return CalendarResult(
                source=self.name,
                status=status,  # type: ignore[arg-type]
                days=days,
                detail=detail,
                latency_ms=int((time.monotonic() - started) * 1000),
            )

        try:
            rpc = await self._call(
                "sk_flex_departure_calendar",
                build_calendar_arguments(origin, destination, anchor, return_date),
            )
            days = tuple(normalize_calendar(rpc))
        except SourceBlocked as blocked:
            return result("paused", blocked.reason)
        except Exception as exc:
            status, detail = self._failure(exc)
            return result(status, detail)
        return result("ok", days=days)

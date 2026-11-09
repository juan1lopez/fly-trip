import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx

from flytrip.core.legs import build_leg, itinerary_id, normalize_flight_number
from flytrip.core.models import Baggage, Itinerary, Leg, Offer, Segment
from flytrip.sources.base import SourceBlocked, SourceRequest, SourceResult

KIWI_URL = "https://mcp.kiwi.com"
# Kiwi acepta rangos de hasta 365 días sin error, pero devuelve solo ~15 resultados
# por consulta: ventanas de 92 días dan más cobertura (ver docs/sources/kiwi.md).
KIWI_MAX_WINDOW_DAYS = 92
# Con adults=2 el campo `price` ya es el total del grupo (ver docs/sources/kiwi.md).
KIWI_PRICE_IS_TOTAL = True

_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


class KiwiToolError(Exception):
    pass


class KiwiProtocolError(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def _kiwi_date(day: date) -> str:
    return day.strftime("%d/%m/%Y")


def split_window(start: date, end: date, max_days: int) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    cursor = start
    while cursor <= end:
        last = min(cursor + timedelta(days=max_days - 1), end)
        windows.append((cursor, last))
        cursor = last + timedelta(days=1)
    return windows


def build_arguments(request: SourceRequest) -> dict[str, object]:
    arguments: dict[str, object] = {
        "flyFrom": request.origin,
        "flyTo": request.destination,
        "departureDate": _kiwi_date(request.depart_from),
        "departureDateTo": _kiwi_date(request.depart_to),
        "adults": request.adults,
        "currency": "USD",
        "locale": "es",
        "sort": "price",
        "allow_self_transfer": request.allow_separate_tickets,
    }
    if request.nights_min is not None and request.nights_max is not None:
        arguments["nights_in_dst_from"] = request.nights_min
        arguments["nights_in_dst_to"] = request.nights_max
    return arguments


def build_rpc_body(arguments: dict[str, object], request_id: int = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": "search-flight", "arguments": arguments},
    }


def parse_sse(text: str) -> dict[str, Any]:
    last: dict[str, Any] | None = None
    for line in text.splitlines():
        if not line.startswith("data:"):
            continue
        try:
            payload = json.loads(line[5:].strip())
        except ValueError:
            continue
        if isinstance(payload, dict) and ("result" in payload or "error" in payload):
            last = payload
    if last is not None:
        return last
    try:
        plain = json.loads(text)
    except ValueError as exc:
        raise KiwiProtocolError("respuesta ilegible") from exc
    if not isinstance(plain, dict):
        raise KiwiProtocolError("respuesta ilegible")
    return plain


def _local(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=None)


def _segment(raw: dict[str, Any]) -> Segment:
    carrier = str(raw["carrier"])
    return Segment(
        carrier_code=carrier,
        carrier_name=str(raw.get("carrierName") or carrier),
        flight_number=normalize_flight_number(carrier, str(raw["flightNumber"])),
        from_airport=str(raw["from"]),
        to_airport=str(raw["to"]),
        departure_local=_local(raw["departureTime"]),
        arrival_local=_local(raw["arrivalTime"]),
    )


def _leg(raw: dict[str, Any]) -> Leg:
    segments = [_segment(s) for s in raw["segments"]]
    return build_leg(segments, int(raw["durationSeconds"]) // 60)


def _structured(rpc: dict[str, Any]) -> dict[str, Any]:
    if rpc.get("error") is not None:
        error = rpc["error"]
        message = error.get("message") if isinstance(error, dict) else error
        raise KiwiToolError(str(message))
    result = rpc.get("result")
    if not isinstance(result, dict):
        raise KiwiProtocolError("respuesta sin resultado")
    content = result.get("content") or [{}]
    text = str(content[0].get("text", ""))
    if result.get("isError"):
        raise KiwiToolError(text or "error desconocido")
    data = result.get("structuredContent")
    if data is None:
        try:
            data = json.loads(text)
        except ValueError as exc:
            raise KiwiProtocolError("respuesta sin datos") from exc
    if not isinstance(data, dict):
        raise KiwiProtocolError("respuesta sin datos")
    if data.get("error") is not None:
        raise KiwiToolError(str(data["error"]))
    return data


def normalize(
    rpc: dict[str, Any], *, origin: str, adults: int, fetched_at: datetime
) -> list[Itinerary]:
    data = _structured(rpc)
    currency = data.get("currency")
    if currency != "USD":
        raise KiwiProtocolError(f"moneda inesperada: {currency}")
    itineraries: list[Itinerary] = []
    for raw in data.get("itineraries") or []:
        outbound = _leg(raw["outbound"])
        inbound = _leg(raw["inbound"]) if raw.get("inbound") else None
        price = Decimal(str(raw["price"]))
        if not KIWI_PRICE_IS_TOTAL:
            price *= adults
        bag = raw.get("baggage")
        baggage = (
            Baggage(
                personal_item=bag.get("personalItem"),
                cabin_bag=bag.get("cabinBag"),
                checked_bag=bag.get("checkedBag"),
            )
            if isinstance(bag, dict)
            else None
        )
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
                        source="kiwi",
                        price_usd=price,
                        booking_url=str(raw["bookingUrl"]),
                        fetched_at=fetched_at,
                    ),
                ),
                baggage=baggage,
                separate_tickets=None,
            )
        )
    return itineraries


class KiwiSource:
    name = "kiwi"

    def __init__(
        self,
        client: httpx.AsyncClient,
        url: str = KIWI_URL,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._client = client
        self._url = url
        self._clock = clock

    def _result(self, status: str, detail: str, fetches: int) -> SourceResult:
        return SourceResult(
            source=self.name,
            status=status,  # type: ignore[arg-type]
            detail=detail,
            fetches=fetches,
        )

    async def search(self, request: SourceRequest) -> SourceResult:
        windows = split_window(request.depart_from, request.depart_to, KIWI_MAX_WINDOW_DAYS)
        found: dict[str, Itinerary] = {}
        fetches = 0
        for start, end in windows:
            window = SourceRequest(
                **{**request.__dict__, "depart_from": start, "depart_to": end},
            )
            body = build_rpc_body(build_arguments(window), request_id=fetches + 1)
            try:
                response = await self._client.post(self._url, json=body, headers=_HEADERS)
            except httpx.TransportError as exc:
                return self._result("error", f"Kiwi no respondió ({type(exc).__name__})", fetches)
            fetches += 1
            if response.status_code == 429:
                raise SourceBlocked("Kiwi limitó las consultas (429)")
            if response.status_code >= 400:
                return self._result("error", f"Kiwi respondió {response.status_code}", fetches)
            try:
                items = normalize(
                    parse_sse(response.text),
                    origin=request.origin,
                    adults=request.adults,
                    fetched_at=self._clock(),
                )
            except (KiwiToolError, KiwiProtocolError) as exc:
                return self._result("error", f"Kiwi: {exc}", fetches)
            for item in items:
                found.setdefault(item.id, item)
        return SourceResult(
            source=self.name,
            status="ok",
            itineraries=tuple(found.values()),
            fetches=fetches,
        )

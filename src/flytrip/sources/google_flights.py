import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol
from urllib.parse import quote

from fli.models import (
    Airport,
    FlightResult,
    FlightSearchFilters,
    FlightSegment,
    MaxStops,
    PassengerInfo,
    SeatType,
    SortBy,
    TripType,
)
from fli.search import (
    SearchClientError,
    SearchConnectionError,
    SearchFlights,
    SearchHTTPError,
    SearchTimeoutError,
)
from fli.search.client import Client
from fli.search.flights import SearchParseError

from flytrip.core.legs import build_leg, itinerary_id, normalize_flight_number
from flytrip.core.models import Itinerary, Offer, Segment
from flytrip.sources.base import BLOCK_PAUSE_MINUTES, SourceBlocked, SourceRequest, SourceResult

GOOGLE_FETCH_BUDGET = 12
GOOGLE_MAX_CONCURRENCY = 3
GOOGLE_RETURN_PAIR_COST = 2
GOOGLE_RATE_LIMITED = "Google Flights limitó las consultas (429)"
# ASSUMED, NOT VERIFIED live: see docs/sources/google-flights.md (question d).
GOOGLE_PRICE_IS_TOTAL = True

RawResults = list[FlightResult | tuple[FlightResult, ...]]


def utc_now() -> datetime:
    return datetime.now(UTC)


class GoogleCurrencyError(Exception):
    def __init__(self, currency: str) -> None:
        super().__init__(currency)
        self.currency = currency


class FliClient(Protocol):
    def search(
        self,
        filters: FlightSearchFilters,
        *,
        top_n: int,
        currency: str,
        language: str,
        country: str,
    ) -> RawResults | None: ...


class _SingleAttemptClient(Client):  # type: ignore[misc]
    """fli's HTTP client without its hidden retries: one fetch is exactly one request.

    fli 0.9.0 decorates `Client.post` with tenacity (3 attempts, exponential wait), so a single
    blocked or failing fetch becomes up to three requests. `__wrapped__` is the undecorated method,
    which keeps the rate limiter, the timeout and the error mapping.
    """

    def post(self, url: str, **kwargs: Any) -> Any:
        return Client.post.__wrapped__(self, url, **kwargs)

    def get(self, url: str, **kwargs: Any) -> Any:
        return Client.get.__wrapped__(self, url, **kwargs)


class RealFliClient:
    def __init__(self) -> None:
        self._client = _SingleAttemptClient()

    def search(
        self,
        filters: FlightSearchFilters,
        *,
        top_n: int,
        currency: str,
        language: str,
        country: str,
    ) -> RawResults | None:
        searcher = SearchFlights()
        searcher.client = self._client
        raw: RawResults | None = searcher.search(
            filters, top_n=top_n, currency=currency, language=language, country=country
        )
        return raw


def _airport(code: str) -> Airport:
    try:
        return Airport[code]
    except KeyError:
        raise ValueError(f"El destino no es un aeropuerto: {code}") from None


def build_filters(request: SourceRequest) -> FlightSearchFilters:
    if request.depart_from != request.depart_to or request.nights_min != request.nights_max:
        raise ValueError("Google solo confirma fechas exactas")
    origin = _airport(request.origin)
    destination = _airport(request.destination)
    segments = [
        FlightSegment(
            departure_airport=[[origin, 0]],
            arrival_airport=[[destination, 0]],
            travel_date=request.depart_from.isoformat(),
        )
    ]
    nights = request.nights_min
    if nights is not None:
        segments.append(
            FlightSegment(
                departure_airport=[[destination, 0]],
                arrival_airport=[[origin, 0]],
                travel_date=(request.depart_from + timedelta(days=nights)).isoformat(),
            )
        )
    return FlightSearchFilters(
        trip_type=TripType.ONE_WAY if nights is None else TripType.ROUND_TRIP,
        passenger_info=PassengerInfo(adults=request.adults),
        flight_segments=segments,
        stops=MaxStops.ANY,
        seat_type=SeatType.ECONOMY,
        sort_by=SortBy.CHEAPEST,
    )


def google_search_url(origin: str, destination: str, depart: date, return_date: date | None) -> str:
    query = f"Flights to {destination} from {origin} on {depart.isoformat()}"
    if return_date is not None:
        query += f" through {return_date.isoformat()}"
    return f"https://www.google.com/travel/flights?q={quote(query)}&curr=USD&hl=es"


def _carrier_code(name: str) -> str:
    """fli's enum member names start with "_" when the IATA code starts with a digit ("_2Z")."""
    return name.removeprefix("_")


def _segments(result: FlightResult) -> list[Segment]:
    segments = []
    for leg in result.legs:
        code = _carrier_code(leg.airline.name)
        segments.append(
            Segment(
                carrier_code=code,
                carrier_name=leg.airline.value,
                flight_number=normalize_flight_number(code, leg.flight_number),
                from_airport=leg.departure_airport.name,
                to_airport=leg.arrival_airport.name,
                departure_local=leg.departure_datetime,
                arrival_local=leg.arrival_datetime,
            )
        )
    return segments


def _separate_tickets(parts: tuple[FlightResult, ...]) -> bool | None:
    flags = [p.self_transfer for p in parts]
    if any(f is True for f in flags):
        return True
    if any(f is False for f in flags):
        return False
    return None


def normalize_results(
    raw: RawResults | None,
    *,
    origin: str,
    destination: str,
    adults: int,
    fetched_at: datetime,
) -> list[Itinerary]:
    itineraries: list[Itinerary] = []
    for item in raw or []:
        parts = item if isinstance(item, tuple) else (item,)
        for part in parts:
            if part.currency not in (None, "USD"):
                raise GoogleCurrencyError(part.currency)
        # Round trips: the last tuple element carries the total price.
        total = parts[-1].price
        if total is None:
            continue
        outbound = build_leg(_segments(parts[0]), parts[0].duration)
        inbound = build_leg(_segments(parts[1]), parts[1].duration) if len(parts) > 1 else None
        back = inbound.segments[0].departure_local.date() if inbound else None
        price = Decimal(str(total))
        if not GOOGLE_PRICE_IS_TOTAL:
            price *= adults
        itineraries.append(
            Itinerary(
                id=itinerary_id(outbound, inbound),
                origin=origin,
                destination=destination,
                trip_type="oneway" if inbound is None else "return",
                outbound=outbound,
                inbound=inbound,
                offers=(
                    Offer(
                        source="google",
                        price_usd=price,
                        booking_url=google_search_url(
                            origin, destination, outbound.segments[0].departure_local.date(), back
                        ),
                        fetched_at=fetched_at,
                    ),
                ),
                baggage=None,
                separate_tickets=_separate_tickets(parts),
            )
        )
    return itineraries


class GoogleFlightsSource:
    name = "google"

    def __init__(
        self,
        client: FliClient,
        clock: Callable[[], datetime] = utc_now,
        max_concurrency: int = GOOGLE_MAX_CONCURRENCY,
    ) -> None:
        self._client = client
        self._clock = clock
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._blocked_until: datetime | None = None

    async def search(self, request: SourceRequest) -> SourceResult:
        fetches = 1 if request.nights_min is None else GOOGLE_RETURN_PAIR_COST
        filters = build_filters(request)
        try:
            async with self._semaphore:
                # Calls queued behind a 429 already passed the engine's pause check.
                if self._blocked_until is not None and self._clock() < self._blocked_until:
                    raise SourceBlocked(GOOGLE_RATE_LIMITED)
                raw = await asyncio.to_thread(
                    self._client.search,
                    filters,
                    top_n=1,
                    currency="USD",
                    language="es",
                    country="AR",
                )
            itineraries = normalize_results(
                raw,
                origin=request.origin,
                destination=request.destination,
                adults=request.adults,
                fetched_at=self._clock(),
            )
        except SearchHTTPError as exc:
            if exc.status_code == 429:
                self._blocked_until = self._clock() + timedelta(minutes=BLOCK_PAUSE_MINUTES)
                raise SourceBlocked(GOOGLE_RATE_LIMITED) from exc
            return self._failure("error", f"Google respondió {exc.status_code}", fetches)
        except SearchTimeoutError:
            return self._failure("timeout", "Google Flights no respondió a tiempo", fetches)
        except SearchConnectionError:
            return self._failure("error", "Sin conexión con Google Flights", fetches)
        except SearchParseError:
            return self._failure("error", "Google cambió el formato de la página", fetches)
        except GoogleCurrencyError as exc:
            return self._failure(
                "error", f"Google devolvió precios en {exc.currency} (moneda inesperada)", fetches
            )
        except SearchClientError:
            return self._failure("error", "Error al consultar Google Flights", fetches)
        return SourceResult(
            source=self.name, status="ok", itineraries=tuple(itineraries), fetches=fetches
        )

    def _failure(self, status: str, detail: str, fetches: int) -> SourceResult:
        return SourceResult(
            source=self.name,
            status=status,  # type: ignore[arg-type]
            detail=detail,
            fetches=fetches,
        )

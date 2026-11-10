"""Which (departure, return) dates Google Flights confirms after Kiwi explored the range."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import chain, zip_longest

from flytrip.core.models import Itinerary
from flytrip.core.query import SearchQuery

FALLBACK_DEPARTURES = 4


@dataclass(frozen=True)
class DatePair:
    origin: str
    destination_airport: str
    depart: date
    return_date: date | None

    @property
    def cost(self) -> int:
        """Google page fetches: the outbound, plus the returns of the cheapest outbound."""
        return 1 if self.return_date is None else 2


def _date_pair(itinerary: Itinerary) -> DatePair:
    outbound = itinerary.outbound.segments
    inbound = itinerary.inbound
    return DatePair(
        origin=itinerary.origin,
        destination_airport=outbound[-1].to_airport,
        depart=outbound[0].departure_local.date(),
        return_date=None if inbound is None else inbound.segments[0].departure_local.date(),
    )


def _fallback_pairs(origin: str, query: SearchQuery) -> list[DatePair]:
    destination = query.destination.strip()
    if not (len(destination) == 3 and destination.isascii() and destination.isalpha()):
        return []  # a city name: without Kiwi results there is no airport to confirm
    span = (query.depart_to - query.depart_from).days
    departs = dict.fromkeys(
        query.depart_from + timedelta(days=round(k * span / (FALLBACK_DEPARTURES + 1)))
        for k in range(1, FALLBACK_DEPARTURES + 1)
    )
    return [
        DatePair(
            origin=origin,
            destination_airport=destination.upper(),
            depart=depart,
            return_date=None
            if query.nights_min is None
            else depart + timedelta(days=query.nights_min),
        )
        for depart in departs
    ]


def _origin_pairs(
    origin: str, itineraries: Sequence[Itinerary], query: SearchQuery
) -> list[DatePair]:
    own = sorted((it for it in itineraries if it.origin == origin), key=lambda it: it.price_usd)
    if not own:
        return _fallback_pairs(origin, query)
    return list(dict.fromkeys(_date_pair(it) for it in own))


def select_google_candidates(
    kiwi_itineraries: Sequence[Itinerary], query: SearchQuery, fetch_budget: int = 12
) -> list[DatePair]:
    """Cheapest distinct date pairs per origin, taken in turns until the budget is spent."""
    queues = [_origin_pairs(origin, kiwi_itineraries, query) for origin in query.origins]
    selected: list[DatePair] = []
    spent = 0
    for pair in chain.from_iterable(zip_longest(*queues)):
        if pair is None:
            continue  # this origin already ran out of pairs
        if spent + pair.cost > fetch_budget:
            break
        selected.append(pair)
        spent += pair.cost
    return selected

from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal

from flytrip.core.models import Itinerary, Offer, TransferCost


def _merge_separate(flags: Sequence[bool | None]) -> bool | None:
    if True in flags:
        return True
    if False in flags:
        return False
    return None


def merge_duplicates(itineraries: Iterable[Itinerary]) -> list[Itinerary]:
    groups: dict[str, list[Itinerary]] = {}
    for it in itineraries:
        groups.setdefault(it.id, []).append(it)
    merged: list[Itinerary] = []
    for group in groups.values():
        seen: set[tuple[str, str]] = set()
        offers: list[Offer] = []
        for it in group:
            for offer in it.offers:
                key = (offer.source, offer.booking_url)
                if key not in seen:
                    seen.add(key)
                    offers.append(offer)
        offers.sort(key=lambda o: o.price_usd)
        baggage = next((it.baggage for it in group if it.baggage is not None), None)
        merged.append(
            group[0].model_copy(
                update={
                    "offers": tuple(offers),
                    "baggage": baggage,
                    "separate_tickets": _merge_separate([it.separate_tickets for it in group]),
                }
            )
        )
    return merged


def mark_separate_tickets(
    all_mode: Sequence[Itinerary], protected_mode: Sequence[Itinerary]
) -> list[Itinerary]:
    protected = {it.id for it in protected_mode}
    return [it.model_copy(update={"separate_tickets": it.id not in protected}) for it in all_mode]


def apply_transfers(
    itineraries: Iterable[Itinerary], transfers: Mapping[str, TransferCost | None]
) -> list[Itinerary]:
    return [it.model_copy(update={"transfer": transfers.get(it.origin)}) for it in itineraries]


def sort_by_total(itineraries: Iterable[Itinerary]) -> list[Itinerary]:
    return sorted(itineraries, key=lambda i: (i.total_from_home_usd, i.travel_hours, i.id))


def best_per_origin(
    itineraries: Sequence[Itinerary], origins: Sequence[str]
) -> dict[str, Itinerary | None]:
    ranked = sort_by_total(itineraries)
    return {o: next((i for i in ranked if i.origin == o), None) for o in origins}


def best_balance(itineraries: Sequence[Itinerary], usd_per_hour: Decimal) -> Itinerary | None:
    if not itineraries:
        return None
    return min(
        itineraries,
        key=lambda i: (
            i.total_from_home_usd + usd_per_hour * i.travel_hours,
            i.total_from_home_usd,
            i.id,
        ),
    )


def keep_true_origin(itineraries: Iterable[Itinerary], origin: str) -> tuple[list[Itinerary], int]:
    """Drop itineraries that do not depart from `origin` (or, round trip, do not return to it)."""
    kept: list[Itinerary] = []
    dropped = 0
    for it in itineraries:
        back_ok = it.inbound is None or it.inbound.segments[-1].to_airport == origin
        if it.outbound.segments[0].from_airport == origin and back_ok:
            kept.append(it)
        else:
            dropped += 1
    return kept, dropped

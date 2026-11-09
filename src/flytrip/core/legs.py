import hashlib
from collections.abc import Sequence

from flytrip.core.models import Layover, Leg, Segment


def normalize_flight_number(carrier_code: str, raw: str) -> str:
    number = raw.replace(" ", "")
    if number.upper().startswith(carrier_code.upper()):
        number = number[len(carrier_code) :]
    return number.lstrip("0")


def build_leg(segments: Sequence[Segment], duration_minutes: int) -> Leg:
    layovers = tuple(
        Layover(
            airport=prev.to_airport,
            minutes=int((nxt.departure_local - prev.arrival_local).total_seconds() // 60),
            overnight=prev.arrival_local.date() != nxt.departure_local.date(),
            airport_change=prev.to_airport != nxt.from_airport,
        )
        for prev, nxt in zip(segments, segments[1:], strict=False)
    )
    return Leg(
        segments=tuple(segments),
        stops=len(segments) - 1,
        layovers=layovers,
        duration_minutes=duration_minutes,
    )


def itinerary_id(outbound: Leg, inbound: Leg | None) -> str:
    legs = [outbound] if inbound is None else [outbound, inbound]
    key = "|".join(
        f"{s.carrier_code}{s.flight_number}@{s.departure_local:%Y-%m-%dT%H:%M}"
        for leg in legs
        for s in leg.segments
    )
    return hashlib.sha1(key.encode()).hexdigest()[:16]

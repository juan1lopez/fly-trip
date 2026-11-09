from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from flytrip.core.legs import build_leg
from flytrip.core.models import Itinerary, Offer, Segment, TransferCost
from flytrip.core.query import SearchQuery

FETCHED = datetime(2026, 11, 9, 15, 0, tzinfo=UTC)


def fixed_clock(iso: str) -> Callable[[], datetime]:
    moment = datetime.fromisoformat(iso)
    return lambda: moment


CLOCK = fixed_clock("2026-11-09T15:00:00+00:00")


def seg(carrier: str, number: str, frm: str, to: str, dep_iso: str, arr_iso: str) -> Segment:
    return Segment(
        carrier_code=carrier,
        carrier_name=carrier,
        flight_number=number,
        from_airport=frm,
        to_airport=to,
        departure_local=datetime.fromisoformat(dep_iso),
        arrival_local=datetime.fromisoformat(arr_iso),
    )


def T(cost: str, hours: str) -> TransferCost:  # noqa: N802
    return TransferCost(cost_usd_roundtrip=Decimal(cost), hours_one_way=Decimal(hours))


def make_itinerary(
    id: str = "X",
    origin: str = "SCL",
    destination: str = "MAD",
    price: str = "758",
    out_minutes: int = 780,
    in_minutes: int = 780,
    transfer: TransferCost | None = None,
    offers: list[tuple[Literal["kiwi", "google"], str, str]] | None = None,
    separate_tickets: bool | None = None,
    trip_type: Literal["oneway", "return"] = "return",
) -> Itinerary:
    outbound = build_leg(
        [seg("IB", "6830", origin, destination, "2027-03-19T00:50", "2027-03-19T17:30")],
        out_minutes,
    )
    inbound = (
        build_leg(
            [seg("IB", "6831", destination, origin, "2027-04-04T23:55", "2027-04-05T08:45")],
            in_minutes,
        )
        if trip_type == "return"
        else None
    )
    raw_offers = offers if offers is not None else [("kiwi", price, "https://kiwi.example/x")]
    return Itinerary(
        id=id,
        origin=origin,
        destination=destination,
        trip_type=trip_type,
        outbound=outbound,
        inbound=inbound,
        offers=tuple(
            Offer(source=s, price_usd=Decimal(p), booking_url=u, fetched_at=FETCHED)
            for s, p, u in raw_offers
        ),
        baggage=None,
        separate_tickets=separate_tickets,
        transfer=transfer,
    )


def make_query(**kw: Any) -> SearchQuery:
    values: dict[str, Any] = {
        "destination": "MAD",
        "origins": ("MDZ", "SCL", "EZE"),
        "depart_from": date(2027, 3, 1),
        "depart_to": date(2027, 5, 31),
        "nights_min": 14,
        "nights_max": 21,
    }
    values.update(kw)
    return SearchQuery(**values)


def fixture(source: str, name: str) -> str:
    return (Path(__file__).parent / "fixtures" / source / name).read_text(encoding="utf-8")

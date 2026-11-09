from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Segment(_Frozen):
    carrier_code: str
    carrier_name: str
    flight_number: str
    from_airport: str
    to_airport: str
    departure_local: datetime
    arrival_local: datetime


class Layover(_Frozen):
    airport: str
    minutes: int
    overnight: bool
    airport_change: bool


class Leg(_Frozen):
    segments: tuple[Segment, ...]
    stops: int
    layovers: tuple[Layover, ...]
    duration_minutes: int


class Baggage(_Frozen):
    personal_item: int | None
    cabin_bag: int | None
    checked_bag: int | None


class Offer(_Frozen):
    source: Literal["kiwi", "google"]
    price_usd: Decimal
    booking_url: str
    fetched_at: datetime


class TransferCost(_Frozen):
    cost_usd_roundtrip: Decimal = Field(ge=0)
    hours_one_way: Decimal = Field(ge=0)


class Itinerary(_Frozen):
    id: str
    origin: str
    destination: str
    trip_type: Literal["oneway", "return"]
    outbound: Leg
    inbound: Leg | None
    offers: tuple[Offer, ...]
    baggage: Baggage | None
    separate_tickets: bool | None
    transfer: TransferCost | None = None

    @property
    def best_offer(self) -> Offer:
        return min(self.offers, key=lambda o: o.price_usd)

    @property
    def price_usd(self) -> Decimal:
        return self.best_offer.price_usd

    @property
    def total_from_home_usd(self) -> Decimal:
        if self.transfer is None:
            return self.price_usd
        return self.price_usd + self.transfer.cost_usd_roundtrip

    @property
    def travel_hours(self) -> Decimal:
        minutes = self.outbound.duration_minutes
        if self.inbound is not None:
            minutes += self.inbound.duration_minutes
        hours = Decimal(minutes) / Decimal(60)
        if self.transfer is not None:
            trips = 2 if self.trip_type == "return" else 1
            hours += self.transfer.hours_one_way * trips
        return hours

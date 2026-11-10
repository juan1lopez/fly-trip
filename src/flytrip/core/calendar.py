"""Month calendar of the cheapest day per date: pure functions over raw (origin, day, price)."""

import calendar
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from flytrip.core.models import TransferCost


class CalendarDay(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: date
    price_usd: Decimal
    origin: str


def build_calendar(
    entries: Iterable[tuple[str, date, Decimal]],
    transfers: Mapping[str, TransferCost | None],
) -> list[CalendarDay]:
    """Cheapest price per day counting each origin's round-trip transfer, sorted by day."""
    best: dict[date, CalendarDay] = {}
    for origin, day, price in entries:
        transfer = transfers.get(origin)
        total = price + (transfer.cost_usd_roundtrip if transfer is not None else Decimal(0))
        current = best.get(day)
        if current is None or total < current.price_usd:
            best[day] = CalendarDay(day=day, price_usd=total, origin=origin)
    return [best[day] for day in sorted(best)]


def cheap_days(days: Sequence[CalendarDay], fraction: Decimal = Decimal("0.1")) -> set[date]:
    """The cheapest `fraction` of the days, and at least one when there is data."""
    if not days:
        return set()
    count = max(1, int(len(days) * fraction))
    ranked = sorted(days, key=lambda d: (d.price_usd, d.day))
    return {d.day for d in ranked[:count]}


def month_grid(year: int, month: int) -> list[list[date | None]]:
    """Weeks (Monday first) of the month; days outside the month are None."""
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    return [[d if d.month == month else None for d in week] for week in weeks]

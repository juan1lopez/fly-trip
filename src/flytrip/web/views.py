"""Presentation helpers shared by the CLI and the web UI."""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from flytrip.core.calendar import cheap_days, month_grid
from flytrip.core.models import Baggage, Itinerary, Leg, TransferCost
from flytrip.core.months import MONTH_NAMES
from flytrip.engine.search import SearchSnapshot, SourceStatus

ORIGIN_LABELS = {
    "MDZ": "Mendoza (todo en avión)",
    "SCL": "Vía Santiago",
    "EZE": "Vía Ezeiza",
}

SOURCE_NAMES = {"kiwi": "Kiwi", "google": "Google Flights", "skiplagged": "Skiplagged"}
UNKNOWN_SEPARATE = "No se pudo verificar si son pasajes separados"


def origin_label(code: str) -> str:
    return ORIGIN_LABELS.get(code, f"Desde {code}")


def format_number(value: Decimal) -> str:
    rounded = int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return f"{rounded:,}".replace(",", ".")


def format_usd(value: Decimal) -> str:
    return f"{format_number(value)} USD"


def format_duration(minutes: int) -> str:
    hours, rest = divmod(minutes, 60)
    if hours == 0:
        return f"{rest} min"
    return f"{hours} h {rest:02d} min" if rest else f"{hours} h"


def format_short_date(d: date) -> str:
    return f"{d:%d/%m}"


def route_label(leg: Leg) -> str:
    airports = [leg.segments[0].from_airport, *(s.to_airport for s in leg.segments)]
    return " → ".join(airports)


def price_breakdown(it: Itinerary, home_airport: str = "MDZ") -> str:
    price = format_number(it.price_usd)
    if it.transfer is not None:
        return f"{price} + {format_number(it.transfer.cost_usd_roundtrip)} traslado"
    if it.origin == home_airport:
        return price
    return f"{price} + traslado (sin configurar)"


def missing_transfer_origins(
    origins: Iterable[str], transfers: Mapping[str, TransferCost | None], home_airport: str = "MDZ"
) -> list[str]:
    """Origins away from home whose transfer is not configured (their total is incomplete)."""
    return [o for o in origins if o != home_airport and transfers.get(o) is None]


def status_label(status: SourceStatus) -> str:
    name = SOURCE_NAMES.get(status.source, status.source)
    match status.state:
        case "ok":
            seconds = f"{(status.latency_ms or 0) / 1000:.1f}".replace(".", ",")
            note = f" — {status.detail}" if status.detail else ""
            return f"{name}: OK ({status.count} en {seconds} s){note}"
        case "partial":
            return f"{name}: parcial — {status.detail}"
        case "paused":
            return f"{name}: en pausa — {status.detail}"
        case "error":
            return f"{name}: error — {status.detail}"
        case "timeout":
            return f"{name}: sin respuesta — {status.detail}"
        case "skipped":
            return f"{name}: omitida — {status.detail}"
        case "pending":
            return f"{name}: esperando"
        case "running":
            return f"{name}: buscando…"


def baggage_label(baggage: Baggage | None) -> str:
    if baggage is None:
        return "desconocido"
    included = [
        label
        for label, count in (
            ("mochila", baggage.personal_item),
            ("cabina", baggage.cabin_bag),
            ("valija", baggage.checked_bag),
        )
        if count
    ]
    return " + ".join(included) if included else "sin equipaje incluido"


def age_label(fetched_at: datetime, now: datetime) -> str:
    minutes = max(0, int((now - fetched_at).total_seconds() // 60))
    if minutes < 1:
        return "hace instantes"
    if minutes < 60:
        return f"hace {minutes} min"
    if minutes < 60 * 24:
        return f"hace {minutes // 60} h"
    return f"hace {minutes // (60 * 24)} d"


@dataclass(frozen=True)
class CalendarCell:
    day: date
    price: Decimal | None = None
    origin: str | None = None
    cheap: bool = False
    cheapest: bool = False  # the cheapest day of its month
    past: bool = False  # before the first day of the search window
    aria_label: str = ""


@dataclass(frozen=True)
class MonthView:
    title: str
    weeks: list[list[CalendarCell | None]]


def best_origin(snapshot: SearchSnapshot) -> str | None:
    """The origin whose best itinerary has the lowest total from home."""
    found = [(it.total_from_home_usd, code) for code, it in snapshot.best_per_origin.items() if it]
    return min(found)[1] if found else None


def _day_label(day: date) -> str:
    return f"{day.day} de {MONTH_NAMES[day.month - 1]} de {day.year}"


def calendar_months(snapshot: SearchSnapshot) -> list[MonthView]:
    """One grid per month of the query window; empty unless the search was in month mode."""
    query = snapshot.query
    if not query.calendar:
        return []
    by_day = {d.day: d for d in snapshot.calendar}
    cheap = cheap_days(snapshot.calendar)
    cheapest_of_month: dict[tuple[int, int], date] = {}
    for ranked in sorted(snapshot.calendar, key=lambda d: (d.price_usd, d.day)):
        cheapest_of_month.setdefault((ranked.day.year, ranked.day.month), ranked.day)
    months: list[MonthView] = []
    year, month = query.depart_from.year, query.depart_from.month
    while (year, month) <= (query.depart_to.year, query.depart_to.month):
        weeks: list[list[CalendarCell | None]] = []
        for week in month_grid(year, month):
            row: list[CalendarCell | None] = []
            for day in week:
                if day is None:
                    row.append(None)
                    continue
                entry = by_day.get(day)
                if entry is None:
                    row.append(CalendarCell(day=day, past=day < query.depart_from))
                    continue
                is_cheapest = cheapest_of_month.get((year, month)) == day
                label = (
                    f"{_day_label(day)}: desde {format_usd(entry.price_usd)}, "
                    f"{origin_label(entry.origin).lower()}, precio orientativo"
                    f"{', el más barato del mes' if is_cheapest else ''}. Buscar este día"
                )
                row.append(
                    CalendarCell(
                        day=day,
                        price=entry.price_usd,
                        origin=entry.origin,
                        cheap=day in cheap,
                        cheapest=is_cheapest,
                        aria_label=label,
                    )
                )
            weeks.append(row)
        title = f"{MONTH_NAMES[month - 1].capitalize()} {year}"
        months.append(MonthView(title=title, weeks=weeks))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def month_options(today: date, count: int = 6) -> list[tuple[str, str]]:
    """(`AAAA-MM`, short label) for the month of tomorrow and the next `count - 1`."""
    options: list[tuple[str, str]] = []
    tomorrow = today + timedelta(days=1)
    year, month = tomorrow.year, tomorrow.month
    for _ in range(count):
        options.append(
            (f"{year:04d}-{month:02d}", f"{MONTH_NAMES[month - 1][:3].capitalize()} {year}")
        )
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return options

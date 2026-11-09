"""Presentation helpers shared by the CLI and the web UI."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from flytrip.core.models import Itinerary, Leg
from flytrip.engine.search import SourceStatus

ORIGIN_LABELS = {
    "MDZ": "Mendoza (todo en avión)",
    "SCL": "Vía Santiago",
    "EZE": "Vía Ezeiza",
}

SOURCE_NAMES = {"kiwi": "Kiwi", "google": "Google Flights"}


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


def status_label(status: SourceStatus) -> str:
    name = SOURCE_NAMES.get(status.source, status.source)
    match status.state:
        case "ok":
            seconds = f"{(status.latency_ms or 0) / 1000:.1f}".replace(".", ",")
            return f"{name}: OK ({status.count} en {seconds} s)"
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

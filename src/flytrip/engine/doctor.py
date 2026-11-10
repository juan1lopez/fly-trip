"""Live health check of the three flight sources, used by `fly doctor`."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from flytrip.core.models import Itinerary
from flytrip.sources.base import PauseRegistry, Source, SourceRequest, SourceResult, run_safely

KIWI_TIMEOUT_S = 20
GOOGLE_TIMEOUT_S = 40
SKIPLAGGED_TIMEOUT_S = 30
PROBE_NIGHTS = 14


@dataclass(frozen=True)
class SourceHealth:
    source: str
    ok: bool
    detail: str
    latency_ms: int


def _itinerary_is_sane(itinerary: Itinerary) -> bool:
    legs = [itinerary.outbound] + ([itinerary.inbound] if itinerary.inbound else [])
    return (
        bool(itinerary.offers)
        and itinerary.price_usd > 0
        and all(offer.booking_url.startswith("https://") for offer in itinerary.offers)
        and all(len(leg.segments) >= 1 for leg in legs)
    )


def check_result_shape(result: SourceResult) -> SourceHealth:
    if result.status != "ok":
        detail = f"Rota: {result.detail}"
        return SourceHealth(result.source, False, detail, result.latency_ms)
    count = len(result.itineraries)
    if count == 0:
        return SourceHealth(result.source, False, "Rota: 0 itinerarios", result.latency_ms)
    if not all(_itinerary_is_sane(i) for i in result.itineraries):
        detail = "Rota: itinerarios con precio, tramos o enlace inválidos"
        return SourceHealth(result.source, False, detail, result.latency_ms)
    seconds = f"{result.latency_ms / 1000:.1f}".replace(".", ",")
    return SourceHealth(
        result.source, True, f"OK: {count} itinerarios en {seconds} s", result.latency_ms
    )


async def run_doctor(
    kiwi: Source,
    google: Source,
    skiplagged: Source | None,
    *,
    today: date,
    pauses: PauseRegistry,
    clock: Callable[[], datetime],
) -> list[SourceHealth]:
    first = today + timedelta(days=30)

    def probe(depart_to: date) -> SourceRequest:
        return SourceRequest(
            origin="SCL",
            destination="MAD",
            depart_from=first,
            depart_to=depart_to,
            nights_min=PROBE_NIGHTS,
            nights_max=PROBE_NIGHTS,
            adults=1,
            allow_separate_tickets=False,
        )

    runs = [
        run_safely(
            kiwi,
            probe(today + timedelta(days=44)),
            timeout_s=KIWI_TIMEOUT_S,
            pauses=pauses,
            clock=clock,
        ),
        run_safely(google, probe(first), timeout_s=GOOGLE_TIMEOUT_S, pauses=pauses, clock=clock),
    ]
    if skiplagged is not None:
        runs.append(
            run_safely(
                skiplagged,
                probe(first),
                timeout_s=SKIPLAGGED_TIMEOUT_S,
                pauses=pauses,
                clock=clock,
            )
        )
    results = await asyncio.gather(*runs)
    return [check_result_shape(r) for r in results]

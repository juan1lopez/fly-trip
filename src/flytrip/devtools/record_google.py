"""Record real Google Flights (`fli`) responses as test fixtures. Hits the network."""

import json
from datetime import date
from pathlib import Path

from flytrip.sources.base import SourceRequest
from flytrip.sources.google_flights import FliClient, RealFliClient, build_filters


def record_google(
    scenario: str,
    origin: str,
    destination: str,
    depart: date,
    nights: int | None,
    adults: int,
    out_dir: Path,
    client: FliClient | None = None,
) -> Path:
    request = SourceRequest(
        origin=origin,
        destination=destination,
        depart_from=depart,
        depart_to=depart,
        nights_min=nights,
        nights_max=nights,
        adults=adults,
        allow_separate_tickets=True,
    )
    filters = build_filters(request)
    raw = (client or RealFliClient()).search(
        filters, top_n=1, currency="USD", language="es", country="AR"
    )
    if not raw:
        raise RuntimeError("Google Flights no devolvió resultados; no se sobrescribe el fixture")
    payload = [
        [r.model_dump(mode="json") for r in item]
        if isinstance(item, tuple)
        else item.model_dump(mode="json")
        for item in raw
    ]
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{scenario}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

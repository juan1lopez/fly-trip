"""Demo engine: the real SearchEngine fed by the recorded fixtures, no network."""

import asyncio
import json
from pathlib import Path

from fli.models import FlightResult

from flytrip.engine.cache import SearchCache
from flytrip.engine.paths import data_dir
from flytrip.engine.search import SearchEngine
from flytrip.engine.settings import SettingsStore
from flytrip.sources.base import PauseRegistry, SourceRequest, SourceResult
from flytrip.sources.google_flights import RawResults, normalize_results
from flytrip.sources.kiwi import normalize, parse_sse, utc_now

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
GOOGLE_DELAY_S = 1.5


def _kiwi_fixture(request: SourceRequest) -> str:
    if request.origin == "MDZ":
        return (
            "madrid_mdz_return_all"
            if request.allow_separate_tickets
            else ("madrid_mdz_return_protected")
        )
    return {"SCL": "madrid_scl_return", "EZE": "madrid_eze_return"}.get(
        request.origin, "madrid_scl_return"
    )


class ReplayKiwi:
    name = "kiwi"

    async def search(self, request: SourceRequest) -> SourceResult:
        text = (FIXTURES / "kiwi" / f"{_kiwi_fixture(request)}.sse").read_text(encoding="utf-8")
        found = normalize(
            parse_sse(text), origin=request.origin, adults=request.adults, fetched_at=utc_now()
        )
        return SourceResult(source=self.name, status="ok", itineraries=tuple(found), fetches=1)


def _load_google(name: str) -> RawResults:
    data = json.loads((FIXTURES / "google" / name).read_text(encoding="utf-8"))
    return [
        tuple(FlightResult.model_validate(part) for part in item)
        if isinstance(item, list)
        else FlightResult.model_validate(item)
        for item in data
    ]


class ReplayGoogle:
    name = "google"

    async def search(self, request: SourceRequest) -> SourceResult:
        await asyncio.sleep(GOOGLE_DELAY_S)
        fixture = "synthetic_oneway.json" if request.nights_min is None else "synthetic_rt.json"
        found = normalize_results(
            _load_google(fixture),
            origin=request.origin,
            destination=request.destination,
            adults=request.adults,
            fetched_at=utc_now(),
        )
        return SourceResult(source=self.name, status="ok", itineraries=tuple(found), fetches=1)


def build_demo_engine(home: Path) -> SearchEngine:
    data = data_dir(home)
    clock = utc_now
    return SearchEngine(
        kiwi=ReplayKiwi(),
        google=ReplayGoogle(),
        settings=SettingsStore(data / "settings.json").load(),
        cache=SearchCache(data / "cache-demo.sqlite", clock),
        pauses=PauseRegistry(data / "pauses-demo.json", clock),
        clock=clock,
    )

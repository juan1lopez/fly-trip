"""Demo engine: the real SearchEngine fed by the recorded fixtures, no network."""

import asyncio
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from fli.models import FlightResult

from flytrip.engine.cache import SearchCache
from flytrip.engine.paths import data_dir
from flytrip.engine.search import SearchEngine
from flytrip.engine.settings import SettingsStore
from flytrip.sources.base import PauseRegistry, SourceRequest, SourceResult
from flytrip.sources.google_flights import RawResults, normalize_results
from flytrip.sources.kiwi import normalize, parse_sse, utc_now
from flytrip.sources.skiplagged import CalendarResult, normalize_calendar, normalize_search

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
GOOGLE_DELAY_S = 1.5
SKIPLAGGED_DELAY_S = 1.0
# The recorded calendar (EZE-MAD) was asked around this anchor; replays shift it to the asked one.
CALENDAR_FIXTURE_ANCHOR = date(2027, 3, 15)


def _kiwi_fixture(request: SourceRequest) -> str | None:
    """The recorded Kiwi answer for the origin, or None: a fixture only answers its own origin."""
    if request.origin == "MDZ":
        return (
            "madrid_mdz_return_all"
            if request.allow_separate_tickets
            else ("madrid_mdz_return_protected")
        )
    return {"SCL": "madrid_scl_return", "EZE": "madrid_eze_return"}.get(request.origin)


def _no_fixture(source: str) -> SourceResult:
    """Nothing recorded for this origin. `raw_count=1` keeps the engine from reading the empty
    answer as a silent block: the demo source did answer, just not for this origin."""
    return SourceResult(source=source, status="ok", fetches=1, raw_count=1)


class ReplayKiwi:
    name = "kiwi"

    async def search(self, request: SourceRequest) -> SourceResult:
        fixture = _kiwi_fixture(request)
        if fixture is None:
            return _no_fixture(self.name)
        text = (FIXTURES / "kiwi" / f"{fixture}.sse").read_text(encoding="utf-8")
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


# The synthetic Google fixtures depart from these airports (round trip, one way).
GOOGLE_FIXTURE_ORIGINS = {"synthetic_rt.json": "SCL", "synthetic_oneway.json": "EZE"}
SKIPLAGGED_FIXTURE_ORIGIN = "SCL"  # madrid_scl_rt.sse


class ReplayGoogle:
    name = "google"

    async def search(self, request: SourceRequest) -> SourceResult:
        await asyncio.sleep(GOOGLE_DELAY_S)
        fixture = "synthetic_oneway.json" if request.nights_min is None else "synthetic_rt.json"
        if request.origin != GOOGLE_FIXTURE_ORIGINS[fixture]:
            return _no_fixture(self.name)
        found = normalize_results(
            _load_google(fixture),
            origin=request.origin,
            destination=request.destination,
            adults=request.adults,
            fetched_at=utc_now(),
        )
        return SourceResult(source=self.name, status="ok", itineraries=tuple(found), fetches=1)


class ReplaySkiplagged:
    name = "skiplagged"

    async def search(self, request: SourceRequest) -> SourceResult:
        await asyncio.sleep(SKIPLAGGED_DELAY_S)
        if request.origin != SKIPLAGGED_FIXTURE_ORIGIN:
            return _no_fixture(self.name)
        text = (FIXTURES / "skiplagged" / "madrid_scl_rt.sse").read_text(encoding="utf-8")
        found = normalize_search(
            parse_sse(text), origin=request.origin, adults=request.adults, fetched_at=utc_now()
        )
        return SourceResult(source=self.name, status="ok", itineraries=tuple(found), fetches=1)

    async def calendar(
        self, origin: str, destination: str, anchor: date, return_date: date | None
    ) -> CalendarResult:
        await asyncio.sleep(SKIPLAGGED_DELAY_S)
        text = (FIXTURES / "skiplagged" / "calendar_eze_mad.sse").read_text(encoding="utf-8")
        shift = anchor - CALENDAR_FIXTURE_ANCHOR
        # A fixed per-origin nudge so the demo origins do not tie on every day.
        nudge = Decimal(sum(map(ord, origin)) % 7 * 15)
        days = tuple(
            (day + shift, price + nudge) for day, price in normalize_calendar(parse_sse(text))
        )
        return CalendarResult(source=self.name, status="ok", days=days)


def build_demo_engine(home: Path) -> SearchEngine:
    data = data_dir(home)
    clock = utc_now
    return SearchEngine(
        kiwi=ReplayKiwi(),
        google=ReplayGoogle(),
        skiplagged=ReplaySkiplagged(),
        settings_provider=SettingsStore(data / "settings.json").load,
        cache=SearchCache(data / "cache-demo.sqlite", clock),
        pauses=PauseRegistry(data / "pauses-demo.json", clock),
        clock=clock,
    )

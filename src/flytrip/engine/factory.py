"""Wires the real search engine: Kiwi over HTTP, Google Flights through `fli`."""

from pathlib import Path

import httpx

from flytrip.engine.cache import SearchCache
from flytrip.engine.paths import data_dir
from flytrip.engine.search import SearchEngine
from flytrip.engine.settings import SettingsStore
from flytrip.sources.base import PauseRegistry
from flytrip.sources.google_flights import GoogleFlightsSource, RealFliClient
from flytrip.sources.kiwi import KiwiSource, utc_now


def build_engine(home: Path) -> SearchEngine:
    data = data_dir(home)
    return SearchEngine(
        kiwi=KiwiSource(httpx.AsyncClient(timeout=20)),
        google=GoogleFlightsSource(RealFliClient()),
        settings_provider=SettingsStore(data / "settings.json").load,
        cache=SearchCache(data / "cache.sqlite", utc_now),
        pauses=PauseRegistry(data / "pauses.json", utc_now),
        clock=utc_now,
    )

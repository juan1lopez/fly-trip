from datetime import UTC, datetime
from typing import Any

import httpx

from flytrip.engine.cache import SearchCache
from flytrip.engine.search import SearchEngine
from flytrip.engine.settings import Settings
from flytrip.sources.base import PauseRegistry
from flytrip.sources.kiwi import KiwiSource

NOW = datetime(2027, 1, 1, tzinfo=UTC)


class Closable:
    def __init__(self, name: str, closed: list[str]) -> None:
        self.name = name
        self._closed = closed

    async def search(self, request: Any) -> Any:
        raise AssertionError

    async def aclose(self) -> None:
        self._closed.append(self.name)


class Plain:
    name = "plain"

    async def search(self, request: Any) -> Any:
        raise AssertionError


async def test_engine_aclose_closes_sources_that_support_it(tmp_path):
    closed: list[str] = []
    engine = SearchEngine(
        kiwi=Closable("kiwi", closed),
        google=Plain(),
        settings_provider=Settings,
        cache=SearchCache(tmp_path / "c.sqlite", lambda: NOW),
        pauses=PauseRegistry(tmp_path / "p.json", lambda: NOW),
        clock=lambda: NOW,
    )
    await engine.aclose()
    assert closed == ["kiwi"]


async def test_kiwi_aclose_closes_client():
    client = httpx.AsyncClient()
    await KiwiSource(client).aclose()
    assert client.is_closed

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fli.models import FlightResult, FlightSearchFilters

from flytrip.core.query import SearchQuery
from flytrip.core.ranking import sort_by_total
from flytrip.engine.search import SearchSnapshot, SnapshotEvent, SourceStatus, StatusEvent
from flytrip.engine.settings import Settings
from flytrip.sources.base import SourceRequest, SourceResult
from tests.factories import CLOCK, T, make_itinerary, make_query


class FakeSource:
    def __init__(
        self,
        name: str,
        results: Callable[[SourceRequest], SourceResult | Exception],
        delay_s: float = 0.0,
    ) -> None:
        self.name = name
        self._results = results
        self._delay_s = delay_s
        self.calls: list[SourceRequest] = []

    async def search(self, request: SourceRequest) -> SourceResult:
        self.calls.append(request)
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        outcome = self._results(request)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


# The only host the web app answers to (TrustedHostMiddleware); TestClient defaults to "testserver".
LOCAL_URL = "http://127.0.0.1:8765"

FLI_FIXTURES = Path(__file__).parent / "fixtures" / "google"


class FakeFli:
    """Stands in for the synchronous `fli` client; never touches the network."""

    def __init__(
        self,
        results: list[FlightResult | tuple[FlightResult, ...]] | None = None,
        raises: Exception | None = None,
    ) -> None:
        self._results = results
        self._raises = raises
        self.calls: list[tuple[FlightSearchFilters, dict[str, Any]]] = []

    def search(
        self, filters: FlightSearchFilters, **kwargs: Any
    ) -> list[FlightResult | tuple[FlightResult, ...]] | None:
        self.calls.append((filters, kwargs))
        if self._raises is not None:
            raise self._raises
        return self._results


SNAPSHOT_A_B_C = SearchSnapshot(
    query=make_query(),
    itineraries=tuple(
        sort_by_total(
            [
                make_itinerary(
                    id="A",
                    origin="SCL",
                    price="758",
                    out_minutes=780,
                    in_minutes=780,
                    transfer=T("80", "7"),
                ),
                make_itinerary(
                    id="B", origin="MDZ", price="934", out_minutes=900, in_minutes=960
                ).model_copy(update={"separate_tickets": True}),
                make_itinerary(
                    id="C",
                    origin="EZE",
                    price="1021",
                    out_minutes=750,
                    in_minutes=780,
                    transfer=T("200", "2"),
                ),
            ]
        )
    ),
    best_per_origin={},
    best_balance=None,
    statuses={
        "kiwi": SourceStatus(source="kiwi", state="ok", latency_ms=2300, count=15),
        "google": SourceStatus(source="google", state="ok", latency_ms=8100, count=3),
    },
    completed_at=CLOCK(),
)


class StaticEngine:
    """An engine that answers every search with one final, fixed snapshot."""

    max_window_days = 365
    settings = Settings()

    def __init__(self, snapshot: SearchSnapshot) -> None:
        self._snapshot = snapshot

    async def run(
        self, query: SearchQuery, *, use_cache: bool = True
    ) -> AsyncIterator[StatusEvent | SnapshotEvent]:
        yield SnapshotEvent(snapshot=self._snapshot, final=True)


def load_fli(name: str) -> list[FlightResult | tuple[FlightResult, ...]]:
    data = json.loads((FLI_FIXTURES / name).read_text(encoding="utf-8"))
    return [
        tuple(FlightResult.model_validate(part) for part in item)
        if isinstance(item, list)
        else FlightResult.model_validate(item)
        for item in data
    ]

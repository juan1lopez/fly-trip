import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fli.models import FlightResult, FlightSearchFilters

from flytrip.sources.base import SourceRequest, SourceResult


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


def load_fli(name: str) -> list[FlightResult | tuple[FlightResult, ...]]:
    data = json.loads((FLI_FIXTURES / name).read_text(encoding="utf-8"))
    return [
        tuple(FlightResult.model_validate(part) for part in item)
        if isinstance(item, list)
        else FlightResult.model_validate(item)
        for item in data
    ]

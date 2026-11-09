import asyncio
from collections.abc import Callable

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

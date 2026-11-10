"""Search engine fixtures: fake Kiwi and Google sources, a movable clock and `collect`."""

from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from flytrip.core.models import Itinerary
from flytrip.engine.cache import SearchCache
from flytrip.engine.search import SearchEngine
from flytrip.engine.settings import Settings
from flytrip.sources.base import PauseRegistry, Source, SourceRequest, SourceResult
from tests.factories import T, itin_on
from tests.fakes import FakeSource

SELF = itin_on("MDZ", "2027-03-10", "2027-03-25", 934).model_copy(update={"id": "SELF"})
PROT = itin_on("MDZ", "2027-03-09", "2027-03-24", 949).model_copy(update={"id": "PROT"})
A = itin_on("SCL", "2027-03-19", "2027-04-04", 758).model_copy(update={"id": "A"})
C = itin_on("EZE", "2027-03-07", "2027-03-26", 1021).model_copy(update={"id": "C"})

Answer = Callable[[SourceRequest], SourceResult | Exception]


async def collect(aiter: AsyncIterator[Any]) -> list[Any]:
    return [item async for item in aiter]


class Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)


def kiwi_answer(*, eze: bool = True) -> Answer:
    """MDZ: [SELF, PROT] in "all" mode and [PROT] in protected mode; SCL: [A]; EZE: [C]."""

    def answer(request: SourceRequest) -> SourceResult:
        found: tuple[Itinerary, ...] = ()
        if request.origin == "MDZ":
            found = (SELF, PROT) if request.allow_separate_tickets else (PROT,)
        elif request.origin == "SCL":
            found = (A,)
        elif request.origin == "EZE" and eze:
            found = (C,)
        return SourceResult(source="kiwi", status="ok", itineraries=found, fetches=1)

    return answer


def google_answer(*, eze: bool = True) -> Answer:
    """One 999 USD itinerary per pair with its own id; MDZ pairs come as separate tickets."""

    def answer(request: SourceRequest) -> SourceResult:
        if request.origin == "EZE" and not eze:
            return SourceResult(source="google", status="ok", fetches=2)
        back = request.depart_from + timedelta(days=request.nights_min or 0)
        base = itin_on(request.origin, request.depart_from.isoformat(), back.isoformat(), 999)
        found = base.model_copy(
            update={
                "id": f"G-{request.origin}-{request.depart_from}",
                "offers": (base.best_offer.model_copy(update={"source": "google"}),),
                "separate_tickets": request.origin == "MDZ",
            }
        )
        return SourceResult(source="google", status="ok", itineraries=(found,), fetches=2)

    return answer


def build_engine(
    tmp_path: Path,
    clock: Clock,
    pauses: PauseRegistry,
    *,
    kiwi: Source,
    google: Source,
    settings: Callable[[], Settings] | None = None,
    skiplagged: Any = None,
    **timeouts: float,
) -> SearchEngine:
    default = Settings(transfers={"SCL": T("80", "7"), "EZE": T("200", "2")})
    return SearchEngine(
        kiwi=kiwi,
        google=google,
        settings_provider=settings or (lambda: default),
        cache=SearchCache(tmp_path / "cache.sqlite", clock),
        pauses=pauses,
        clock=clock,
        skiplagged=skiplagged,
        **timeouts,
    )


@pytest.fixture
def clock() -> Clock:
    return Clock(datetime(2026, 11, 9, 15, 0, tzinfo=UTC))


@pytest.fixture
def pauses(tmp_path: Path, clock: Clock) -> PauseRegistry:
    return PauseRegistry(tmp_path / "pauses.json", clock)


@pytest.fixture
def engine(tmp_path: Path, clock: Clock, pauses: PauseRegistry) -> SearchEngine:
    return build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", kiwi_answer()),
        google=FakeSource("google", google_answer(), delay_s=0.3),
    )


@pytest.fixture
def slow_engine(tmp_path: Path, clock: Clock, pauses: PauseRegistry) -> SearchEngine:
    return build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", kiwi_answer(), delay_s=5),
        google=FakeSource("google", google_answer(), delay_s=0.3),
        hard_timeout_s=0.2,
    )


@pytest.fixture
def engine_without_eze_results(tmp_path: Path, clock: Clock, pauses: PauseRegistry) -> SearchEngine:
    return build_engine(
        tmp_path,
        clock,
        pauses,
        kiwi=FakeSource("kiwi", kiwi_answer(eze=False)),
        google=FakeSource("google", google_answer(eze=False), delay_s=0.3),
    )

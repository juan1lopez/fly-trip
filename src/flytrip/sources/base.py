import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from flytrip.core.models import Itinerary
from flytrip.core.query import MENDOZA_TZ

BLOCK_PAUSE_MINUTES = 60


@dataclass(frozen=True)
class SourceRequest:
    origin: str
    destination: str
    depart_from: date
    depart_to: date
    nights_min: int | None
    nights_max: int | None
    adults: int
    allow_separate_tickets: bool


@dataclass(frozen=True)
class SourceResult:
    source: str
    status: Literal["ok", "paused", "error", "timeout"]
    itineraries: tuple[Itinerary, ...] = ()
    detail: str = ""
    latency_ms: int = 0
    fetches: int = 0
    # What the API itself returned (cards), when the source knows; None means "same as itineraries".
    raw_count: int | None = None
    # Results the source or the engine threw away (wrong origin, hidden city, wrong shape).
    dropped: int = 0


class Source(Protocol):
    name: str

    async def search(self, request: SourceRequest) -> SourceResult: ...


class SourceBlocked(Exception):  # noqa: N818
    def __init__(self, reason: str, pause_minutes: int = BLOCK_PAUSE_MINUTES) -> None:
        super().__init__(reason)
        self.reason = reason
        self.pause_minutes = pause_minutes


class PauseRegistry:
    def __init__(self, path: Path, clock: Callable[[], datetime]) -> None:
        self._path = path
        self._clock = clock
        self._memory: dict[str, dict[str, str]] = {}

    def _load(self) -> dict[str, dict[str, str]]:
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def pause(self, source: str, minutes: int, reason: str) -> None:
        until = self._clock() + timedelta(minutes=minutes)
        entry = {"until": until.isoformat(), "reason": reason}
        self._memory[source] = entry
        try:
            data = self._load()
            data[source] = entry
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except (OSError, TypeError, ValueError):
            pass  # best effort: the in-memory pause still applies

    def active_pause(self, source: str) -> tuple[datetime, str] | None:
        try:
            entry = self._memory.get(source) or self._load().get(source)
            if not isinstance(entry, dict):
                return None
            until = datetime.fromisoformat(entry["until"])
            reason = str(entry["reason"])
            if until.tzinfo is None or until <= self._clock():
                return None
        except Exception:
            return None
        return until, reason


def _paused_result(source: str, until: datetime, reason: str, latency_ms: int) -> SourceResult:
    hhmm = until.astimezone(MENDOZA_TZ).strftime("%H:%M")
    return SourceResult(
        source=source,
        status="paused",
        detail=f"En pausa hasta las {hhmm}: {reason}",
        latency_ms=latency_ms,
    )


async def run_safely(
    source: Source,
    request: SourceRequest,
    *,
    timeout_s: float,
    pauses: PauseRegistry,
    clock: Callable[[], datetime],
) -> SourceResult:
    started = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - started) * 1000)

    active = pauses.active_pause(source.name)
    if active is not None:
        return _paused_result(source.name, active[0], active[1], elapsed_ms())
    try:
        result = await asyncio.wait_for(source.search(request), timeout=timeout_s)
    except SourceBlocked as blocked:
        pauses.pause(source.name, blocked.pause_minutes, blocked.reason)
        until = clock() + timedelta(minutes=blocked.pause_minutes)
        return _paused_result(source.name, until, blocked.reason, elapsed_ms())
    except TimeoutError:
        return SourceResult(
            source=source.name,
            status="timeout",
            detail=f"No respondió en {timeout_s:.0f} s",
            latency_ms=elapsed_ms(),
        )
    except Exception as exc:
        return SourceResult(
            source=source.name,
            status="error",
            detail=f"Error inesperado ({type(exc).__name__})",
            latency_ms=elapsed_ms(),
        )
    return replace(result, latency_ms=elapsed_ms())

import asyncio
import json
from datetime import date

import pytest

from flytrip.sources.base import (
    PauseRegistry,
    SourceBlocked,
    SourceRequest,
    SourceResult,
    run_safely,
)
from tests.factories import CLOCK, fixed_clock
from tests.fakes import FakeSource

REQ = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 1),
    depart_to=date(2027, 5, 31),
    nights_min=14,
    nights_max=21,
    adults=1,
    allow_separate_tickets=True,
)


def _pauses(tmp_path, clock=CLOCK):
    return PauseRegistry(tmp_path / "p.json", clock)


async def test_ok_result_gets_latency(tmp_path):
    src = FakeSource("fake", lambda r: SourceResult(source="fake", status="ok", fetches=2))
    r = await run_safely(src, REQ, timeout_s=1, pauses=_pauses(tmp_path), clock=CLOCK)
    assert (r.status, r.fetches) == ("ok", 2)
    assert src.calls == [REQ]


async def test_unexpected_exception_becomes_error(tmp_path):
    src = FakeSource("fake", lambda r: ValueError("x"))
    r = await run_safely(src, REQ, timeout_s=1, pauses=_pauses(tmp_path), clock=CLOCK)
    assert (r.status, r.detail) == ("error", "Error inesperado (ValueError)")


async def test_timeout(tmp_path):
    src = FakeSource("slow", lambda r: SourceResult(source="slow", status="ok"), delay_s=5)
    r = await run_safely(src, REQ, timeout_s=1, pauses=_pauses(tmp_path), clock=CLOCK)
    assert (r.status, r.detail) == ("timeout", "No respondió en 1 s")


async def test_blocked_pauses_for_60_minutes_and_persists(tmp_path):
    pauses = _pauses(tmp_path)
    r = await run_safely(
        FakeSource("g", lambda r: SourceBlocked("429")),
        REQ,
        timeout_s=1,
        pauses=pauses,
        clock=CLOCK,
    )
    assert (r.status, r.detail) == ("paused", "En pausa hasta las 13:00: 429")
    assert PauseRegistry(tmp_path / "p.json", CLOCK).active_pause("g") is not None
    later = fixed_clock("2026-11-09T16:01:00+00:00")
    assert PauseRegistry(tmp_path / "p.json", later).active_pause("g") is None


async def test_paused_source_is_not_called(tmp_path):
    pauses = _pauses(tmp_path)
    pauses.pause("g", 30, "429")
    src = FakeSource("g", lambda r: SourceResult(source="g", status="ok"))
    r = await run_safely(src, REQ, timeout_s=1, pauses=pauses, clock=CLOCK)
    assert (r.status, r.detail) == ("paused", "En pausa hasta las 12:30: 429")
    assert src.calls == []


async def test_cancellation_propagates(tmp_path):
    src = FakeSource("slow", lambda r: SourceResult(source="slow", status="ok"), delay_s=5)
    task = asyncio.create_task(
        run_safely(src, REQ, timeout_s=10, pauses=_pauses(tmp_path), clock=CLOCK)
    )
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


def test_corrupt_pause_file_means_no_pauses(tmp_path):
    path = tmp_path / "sub" / "p.json"
    path.parent.mkdir()
    path.write_text("{not json", encoding="utf-8")
    pauses = PauseRegistry(path, CLOCK)
    assert pauses.active_pause("g") is None
    pauses.pause("g", 5, "x")
    assert json.loads(path.read_text(encoding="utf-8"))
    assert pauses.active_pause("g") is not None


def test_creates_parent_directories(tmp_path):
    path = tmp_path / "a" / "b" / "p.json"
    PauseRegistry(path, CLOCK).pause("g", 5, "x")
    assert path.exists()

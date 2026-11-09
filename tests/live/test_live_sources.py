from datetime import UTC, datetime

import pytest

from flytrip.core.query import today_in_mendoza
from flytrip.engine.doctor import run_doctor
from flytrip.engine.factory import build_engine
from flytrip.sources.base import PauseRegistry
from flytrip.sources.kiwi import utc_now


@pytest.mark.live
async def test_live_sources_are_healthy(tmp_path):
    engine = build_engine(tmp_path)
    health = await run_doctor(
        engine.kiwi,
        engine.google,
        today=today_in_mendoza(datetime.now(UTC)),
        pauses=PauseRegistry(tmp_path / "p.json", utc_now),
        clock=utc_now,
    )
    assert {h.source: h.ok for h in health}["kiwi"] is True

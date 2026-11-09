from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from flytrip.engine.search import SearchSnapshot
from flytrip.engine.settings import SettingsStore
from flytrip.web.app import create_app
from tests.fakes import SNAPSHOT_A_B_C, StaticEngine


@pytest.fixture
def settings_store(tmp_path: Path) -> SettingsStore:
    return SettingsStore(tmp_path / "settings.json")


def _client(snapshot: SearchSnapshot, store: SettingsStore) -> TestClient:
    app = create_app(engine_factory=lambda: StaticEngine(snapshot), settings_store=store)
    return TestClient(app)


@pytest.fixture
def client(settings_store: SettingsStore) -> TestClient:
    return _client(SNAPSHOT_A_B_C, settings_store)


@pytest.fixture
def client_without_eze(settings_store: SettingsStore) -> TestClient:
    kept = tuple(it for it in SNAPSHOT_A_B_C.itineraries if it.origin != "EZE")
    snapshot = SNAPSHOT_A_B_C.model_copy(
        update={
            "itineraries": kept,
            "best_per_origin": {
                "MDZ": next(it for it in kept if it.origin == "MDZ"),
                "SCL": next(it for it in kept if it.origin == "SCL"),
                "EZE": None,
            },
        }
    )
    return _client(snapshot, settings_store)


def sse_events(client: TestClient, url: str) -> list[tuple[str, str]]:
    """Parse a finished event stream into (event, data) pairs, joining `data:` lines."""
    body = client.get(url).text
    events: list[tuple[str, str]] = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        name, data = "message", []
        for line in block.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].removeprefix(" "))
        if data or name != "message":
            events.append((name, "\n".join(data)))
    return events

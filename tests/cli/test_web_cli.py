import socket
from pathlib import Path

from fastapi.testclient import TestClient

from flytrip.cli import find_free_port, make_web_app
from flytrip.engine.settings import SettingsStore
from tests.fakes import SNAPSHOT_A_B_C, StaticEngine

ROOT = Path(__file__).resolve().parents[2]
URL = (
    "/buscar/stream?destino=MAD&desde=2027-03-01&hasta=2027-05-31&noches_min=14&noches_max=21"
    "&origenes=MDZ&adultos=1"
)


def test_find_free_port_skips_busy():
    busy = socket.socket()
    busy.bind(("127.0.0.1", 0))
    port = busy.getsockname()[1]
    busy.listen(1)
    try:
        assert find_free_port(port) > port
    finally:
        busy.close()


def test_launcher_runs_fly_web():
    text = (ROOT / "Buscar vuelos.cmd").read_text(encoding="utf-8")
    assert 'cd /d "%~dp0"' in text and "uv run fly web" in text
    assert text.splitlines() == [
        "@echo off",
        'cd /d "%~dp0"',
        "uv run fly web",
        "if errorlevel 1 pause",
    ]


def test_web_app_reuses_one_engine_across_requests(tmp_path):
    engine = StaticEngine(SNAPSHOT_A_B_C)
    calls: list[StaticEngine] = []
    original = engine.run

    def spy(*args, **kwargs):
        calls.append(engine)
        return original(*args, **kwargs)

    engine.run = spy  # type: ignore[method-assign]
    app = make_web_app(engine, SettingsStore(tmp_path / "settings.json"))
    with TestClient(app) as client:
        assert client.get(URL).status_code == 200
        assert client.get(URL).status_code == 200
    assert len(calls) == 2 and calls[0] is calls[1] is engine

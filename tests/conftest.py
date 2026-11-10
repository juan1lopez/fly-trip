import pytest
from pytest_socket import socket_allow_hosts

LOCAL_HOSTS = ["127.0.0.1", "localhost", "::1"]
TEST_TODAY = "2026-11-09"


@pytest.fixture(autouse=True)
def _fixed_today(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fixed test dates (2027) must not age: validation sees this day, also in subprocesses."""
    monkeypatch.setenv("FLYTRIP_TODAY", TEST_TODAY)


@pytest.fixture(autouse=True)
def _network_guard(request: pytest.FixtureRequest) -> None:
    """Tests never reach the internet; only `live` tests may.

    Not using --disable-socket: asyncio on Windows needs local sockets.
    """
    if request.node.get_closest_marker("live"):
        return
    socket_allow_hosts(LOCAL_HOSTS, allow_unix_socket=True)

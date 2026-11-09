import pytest
from pytest_socket import socket_allow_hosts

LOCAL_HOSTS = ["127.0.0.1", "localhost", "::1"]


@pytest.fixture(autouse=True)
def _network_guard(request: pytest.FixtureRequest) -> None:
    """Tests never reach the internet; only `live` tests may.

    Not using --disable-socket: asyncio on Windows needs local sockets.
    """
    if request.node.get_closest_marker("live"):
        return
    socket_allow_hosts(LOCAL_HOSTS, allow_unix_socket=True)

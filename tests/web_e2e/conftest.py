import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from pathlib import Path

import pytest


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture
def demo_server(tmp_path: Path) -> Iterator[str]:
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "flytrip", "web", "--demo", "--no-abrir", "--puerto", str(port)],
        env={**os.environ, "FLYTRIP_HOME": str(tmp_path), "FLYTRIP_TODAY": "2026-11-09"},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 20
    try:
        while True:
            if proc.poll() is not None:
                raise RuntimeError(f"fly web terminó con código {proc.returncode}")
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError("fly web no abrió el puerto en 20 s") from None
                time.sleep(0.2)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

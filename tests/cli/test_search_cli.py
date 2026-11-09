import os
import subprocess
import sys

from typer.testing import CliRunner

from flytrip import cli
from flytrip.engine.search import SearchSnapshot
from tests.fakes import SNAPSHOT_A_B_C, StaticEngine

ARGS = ["search", "MAD", "--desde", "2027-03-01", "--hasta", "2027-05-31", "--noches", "14-21"]


def test_search_table_shows_totals_and_warning(monkeypatch):
    monkeypatch.setattr(cli, "engine_factory", lambda home: StaticEngine(SNAPSHOT_A_B_C))
    result = CliRunner().invoke(cli.app, ARGS)
    assert result.exit_code == 0
    assert "838 USD" in result.output and "758 + 80 traslado" in result.output
    assert "SCL → MAD" in result.output and "⚠" in result.output
    assert "Kiwi: OK (15 en 2,3 s)" in result.output


def test_search_json_is_a_snapshot(monkeypatch):
    monkeypatch.setattr(cli, "engine_factory", lambda home: StaticEngine(SNAPSHOT_A_B_C))
    out = CliRunner().invoke(cli.app, [*ARGS, "--json"]).output
    assert SearchSnapshot.model_validate_json(out).itineraries[0].id == "A"


def test_invalid_query_exits_2_in_spanish(monkeypatch):
    monkeypatch.setattr(cli, "engine_factory", lambda home: StaticEngine(SNAPSHOT_A_B_C))
    r = CliRunner().invoke(
        cli.app, ["search", "MAD", "--desde", "2027-05-31", "--hasta", "2027-03-01", "--solo-ida"]
    )
    assert r.exit_code == 2 and "La fecha 'hasta' no puede ser anterior a 'desde'." in r.output


def test_search_output_survives_cp1252(tmp_path):
    env = {**os.environ, "PYTHONIOENCODING": "cp1252", "FLYTRIP_HOME": str(tmp_path)}
    proc = subprocess.run(
        [sys.executable, "-m", "flytrip", *ARGS, "--demo"],
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert b"UnicodeEncodeError" not in proc.stderr

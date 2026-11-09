from types import SimpleNamespace

from typer.testing import CliRunner

from flytrip import cli
from flytrip.sources.base import SourceResult
from tests.factories import make_itinerary
from tests.fakes import FakeSource


def _engine(google_result: SourceResult) -> SimpleNamespace:
    kiwi = FakeSource(
        "kiwi", lambda r: SourceResult(source="kiwi", status="ok", itineraries=(make_itinerary(),))
    )
    return SimpleNamespace(kiwi=kiwi, google=FakeSource("google", lambda r: google_result))


def test_doctor_exits_1_when_a_source_is_broken(monkeypatch, tmp_path):
    monkeypatch.setenv("FLYTRIP_HOME", str(tmp_path))
    broken = SourceResult(source="google", status="error", detail="Google cambió el formato")
    monkeypatch.setattr(cli, "engine_factory", lambda home: _engine(broken))
    result = CliRunner().invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "Kiwi" in result.output and "Rota: Google cambió el formato" in result.output


def test_doctor_exits_0_when_all_healthy(monkeypatch, tmp_path):
    monkeypatch.setenv("FLYTRIP_HOME", str(tmp_path))
    good = SourceResult(source="google", status="ok", itineraries=(make_itinerary(),))
    monkeypatch.setattr(cli, "engine_factory", lambda home: _engine(good))
    result = CliRunner().invoke(cli.app, ["doctor"])
    assert result.exit_code == 0 and "OK: 1 itinerarios" in result.output

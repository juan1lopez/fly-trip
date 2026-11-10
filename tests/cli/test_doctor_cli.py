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


def test_doctor_reports_format_changes_of_both_real_sources(monkeypatch, tmp_path):
    import httpx
    import respx
    from fli.search.flights import SearchParseError

    from flytrip.sources.google_flights import GoogleFlightsSource
    from flytrip.sources.kiwi import KIWI_URL, KiwiSource
    from tests.fakes import FakeFli

    monkeypatch.setenv("FLYTRIP_HOME", str(tmp_path))
    with respx.mock(assert_all_called=False) as router:
        router.post(KIWI_URL).mock(return_value=httpx.Response(200, text="data: {not json\n\n"))
        engine = SimpleNamespace(
            kiwi=KiwiSource(httpx.AsyncClient()),
            google=GoogleFlightsSource(FakeFli(raises=SearchParseError("shape changed"))),
        )
        monkeypatch.setattr(cli, "engine_factory", lambda home: engine)
        result = CliRunner().invoke(cli.app, ["doctor"])
    assert result.exit_code == 1
    assert "Rota: Kiwi: respuesta" in result.output
    assert "Rota: Google cambió el formato de la página" in result.output

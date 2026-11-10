import os
import subprocess
import sys
from datetime import date

from typer.testing import CliRunner

from flytrip import cli
from flytrip.engine.search import SearchSnapshot
from flytrip.engine.settings import Settings
from tests.factories import T
from tests.fakes import SNAPSHOT_A_B_C, StaticEngine

ARGS = ["search", "MAD", "--desde", "2027-03-01", "--hasta", "2027-05-31", "--noches", "14-21"]


def test_search_table_shows_totals_and_warning(monkeypatch):
    monkeypatch.setattr(cli, "engine_factory", lambda home: StaticEngine(SNAPSHOT_A_B_C))
    result = CliRunner().invoke(cli.app, ARGS)
    assert result.exit_code == 0
    assert "838 USD" in result.output and "758 + 80 traslado" in result.output
    assert "SCL → MAD" in result.output and "⚠" in result.output
    assert "Kiwi: OK (15 en 2,3 s)" in result.output


def test_search_marks_unknown_separate_tickets_and_failed_origins(monkeypatch):
    snapshot = SNAPSHOT_A_B_C.model_copy(update={"failed_origins": {"EZE": "Kiwi respondió 500"}})
    monkeypatch.setattr(cli, "engine_factory", lambda home: StaticEngine(snapshot))
    out = CliRunner().invoke(cli.app, ARGS).output
    assert "No se pudo verificar si son pasajes separados" in out
    assert "No se pudo consultar Vía Ezeiza: Kiwi respondió 500" in out


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
    env = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "FLYTRIP_HOME": str(tmp_path),
        "FLYTRIP_TODAY": "2026-11-09",
    }
    proc = subprocess.run(
        [sys.executable, "-m", "flytrip", *ARGS, "--demo"],
        env=env,
        capture_output=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert b"UnicodeEncodeError" not in proc.stderr


def test_search_requires_exactly_one_of_nights_or_one_way(monkeypatch):
    monkeypatch.setattr(cli, "engine_factory", lambda home: StaticEngine(SNAPSHOT_A_B_C))
    base = ["search", "MAD", "--desde", "2027-03-01", "--hasta", "2027-05-31"]
    neither = CliRunner().invoke(cli.app, base)
    assert neither.exit_code == 2
    assert "Indica noches mínimas y máximas, o marca solo ida." in neither.output
    both = CliRunner().invoke(cli.app, [*base, "--noches", "14-21", "--solo-ida"])
    assert both.exit_code == 2 and "Usa --noches o --solo-ida, no los dos." in both.output


def test_search_without_snapshot_exits_1_in_spanish(monkeypatch):
    class EmptyEngine(StaticEngine):
        async def run(self, query, *, use_cache=True):
            return
            yield

    monkeypatch.setattr(cli, "engine_factory", lambda home: EmptyEngine(SNAPSHOT_A_B_C))
    r = CliRunner().invoke(cli.app, ARGS)
    assert r.exit_code == 1 and "La búsqueda terminó sin resultados." in r.output
    assert "Traceback" not in r.output


def test_cli_validation_uses_the_today_seam(monkeypatch):
    monkeypatch.setattr(cli, "engine_factory", lambda home: StaticEngine(SNAPSHOT_A_B_C))
    monkeypatch.setenv("FLYTRIP_TODAY", "2027-06-01")
    r = CliRunner().invoke(cli.app, ARGS)
    assert r.exit_code == 2 and "La fecha 'desde' tiene que ser posterior a hoy." in r.output


def test_search_warns_when_a_transfer_is_not_configured(monkeypatch):
    monkeypatch.setattr(cli, "engine_factory", lambda home: StaticEngine(SNAPSHOT_A_B_C))
    out = CliRunner().invoke(cli.app, ARGS).output
    assert "Configura el traslado a Santiago/Ezeiza en Ajustes" in out
    configured = StaticEngine(SNAPSHOT_A_B_C)
    configured.settings = Settings(transfers={"SCL": T("80", "7"), "EZE": T("200", "2")})
    monkeypatch.setattr(cli, "engine_factory", lambda home: configured)
    assert "Configura el traslado" not in CliRunner().invoke(cli.app, ARGS).output


class CapturingEngine(StaticEngine):
    last_query = None

    async def run(self, query, *, use_cache=True):
        CapturingEngine.last_query = query
        async for event in super().run(query, use_cache=use_cache):
            yield event


def _month_run(monkeypatch, *args):
    CapturingEngine.last_query = None
    monkeypatch.setattr(cli, "engine_factory", lambda home: CapturingEngine(SNAPSHOT_A_B_C))
    return CliRunner().invoke(cli.app, ["search", "MAD", *args])


def test_month_mode_builds_a_calendar_query(monkeypatch):
    r = _month_run(monkeypatch, "--mes", "2027-03", "--hasta-mes", "2027-05", "--noches", "14-21")
    assert r.exit_code == 0, r.output
    q = CapturingEngine.last_query
    assert q.calendar is True
    assert (q.depart_from, q.depart_to) == (date(2027, 3, 1), date(2027, 5, 31))


def test_month_mode_current_month_starts_tomorrow(monkeypatch):
    r = _month_run(monkeypatch, "--mes", "2026-11", "--solo-ida")
    assert r.exit_code == 0, r.output
    q = CapturingEngine.last_query
    assert (q.depart_from, q.depart_to) == (date(2026, 11, 10), date(2026, 11, 30))
    assert q.trip_type == "oneway"


def test_date_mode_is_not_calendar(monkeypatch):
    r = _month_run(monkeypatch, *ARGS[2:])
    assert r.exit_code == 0 and CapturingEngine.last_query.calendar is False


def test_mes_and_dates_are_exclusive(monkeypatch):
    r = _month_run(monkeypatch, "--mes", "2027-03", "--desde", "2027-03-01", "--solo-ida")
    assert r.exit_code == 2 and "Usa --mes o --desde/--hasta, no los dos." in r.output
    r = _month_run(monkeypatch, "--mes", "2027-03", "--hasta", "2027-04-01", "--solo-ida")
    assert r.exit_code == 2 and "Usa --mes o --desde/--hasta, no los dos." in r.output


def test_month_mode_still_needs_nights_or_one_way(monkeypatch):
    r = _month_run(monkeypatch, "--mes", "2027-03")
    assert r.exit_code == 2 and "Indica noches mínimas y máximas, o marca solo ida." in r.output


def test_month_mode_validation_messages(monkeypatch):
    r = _month_run(monkeypatch, "--mes", "2026-10", "--solo-ida")
    assert r.exit_code == 2 and "Ese mes ya pasó: 2026-10." in r.output
    r = _month_run(monkeypatch, "--mes", "2027-13", "--solo-ida")
    assert r.exit_code == 2 and "Mes inválido: 2027-13. Usa AAAA-MM." in r.output
    r = _month_run(monkeypatch, "--mes", "2027-01", "--hasta-mes", "2027-06", "--solo-ida")
    assert r.exit_code == 2 and "Puedes elegir hasta 4 meses." in r.output


def test_hasta_mes_without_mes_and_missing_dates_exit_2(monkeypatch):
    r = _month_run(monkeypatch, "--hasta-mes", "2027-04", "--solo-ida")
    assert r.exit_code == 2
    r = _month_run(monkeypatch, "--solo-ida")
    assert r.exit_code == 2 and "Indica --mes o --desde y --hasta." in r.output


def test_month_search_prints_one_cheapest_day_line_per_month(monkeypatch):
    from decimal import Decimal

    from flytrip.core.calendar import CalendarDay

    snapshot = SNAPSHOT_A_B_C.model_copy(
        update={
            "calendar": (
                CalendarDay(day=date(2027, 3, 9), price_usd=Decimal("954"), origin="EZE"),
                CalendarDay(day=date(2027, 3, 12), price_usd=Decimal("1100"), origin="MDZ"),
                CalendarDay(day=date(2027, 4, 2), price_usd=Decimal("1001"), origin="SCL"),
            )
        }
    )
    monkeypatch.setattr(cli, "engine_factory", lambda home: StaticEngine(snapshot))
    month_args = ["--mes", "2027-03", "--hasta-mes", "2027-04", "--noches", "14-21"]
    r = CliRunner().invoke(cli.app, ["search", "MAD", *month_args])
    assert r.exit_code == 0, r.output
    assert "Día más barato de marzo: 09/03 desde EZE · 954 USD (orientativo)" in r.output
    assert "Día más barato de abril: 02/04 desde SCL · 1.001 USD (orientativo)" in r.output

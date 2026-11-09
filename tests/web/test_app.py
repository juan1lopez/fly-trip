from datetime import UTC, datetime
from html import unescape

from tests.factories import T
from tests.web.conftest import sse_events

QS = (
    "destino=MAD&desde=2027-03-01&hasta=2027-05-31&noches_min=14&noches_max=21"
    "&origenes=MDZ&origenes=SCL&origenes=EZE&adultos=1&separados=1"
)


def _results(client, qs=QS):
    return "".join(d for e, d in sse_events(client, "/buscar/stream?" + qs) if e == "results")


def test_index_prefills_defaults(client):
    html = client.get("/").text
    for code in ("MDZ", "SCL", "EZE"):
        assert f'value="{code}" checked' in html
    assert 'name="adultos" value="1"' in html


def test_stream_emits_status_then_results_then_done(client):
    names = [e for e, _ in sse_events(client, "/buscar/stream?" + QS)]
    assert names[0] == "status" and "results" in names and names[-1] == "done"


def test_results_show_breakdown_and_separate_warning(client):
    html = _results(client)
    assert "758 + 80 traslado" in html and "Pasajes separados" in html
    assert "Comprar en Kiwi" in html
    assert html.count('class="itinerary"') == 3 and 'class="origin-card"' in html
    assert "desconocido" in html


def test_empty_origin_card_shows_message(client_without_eze):
    html = _results(client_without_eze)
    assert "Vía Ezeiza" in html and "Sin resultados para este origen" in html


def test_validation_error_is_spanish_422(client):
    r = client.get("/buscar/stream?" + QS.replace("desde=2027-03-01", "desde=2020-01-01"))
    assert r.status_code == 422
    assert "La fecha 'desde' tiene que ser posterior a hoy." in unescape(r.text)


def test_settings_post_persists_transfers(client, settings_store):
    client.post(
        "/ajustes",
        data={"traslado_SCL_costo": "80", "traslado_SCL_horas": "7", "usd_por_hora": "10"},
    )
    assert settings_store.load().transfers["SCL"] == T("80", "7")


def test_settings_post_with_invalid_data_shows_spanish_error(client, settings_store):
    r = client.post("/ajustes", data={"traslado_SCL_costo": "abc", "usd_por_hora": "10"})
    assert "inválid" in r.text and settings_store.load().transfers["SCL"] is None


def test_validate_returns_204_for_valid_query(client):
    assert client.get("/buscar/validar?" + QS).status_code == 204


def test_validate_returns_spanish_422_for_invalid_query(client):
    r = client.get("/buscar/validar?" + QS.replace("desde=2027-03-01", "desde=2020-01-01"))
    assert r.status_code == 422
    assert "La fecha 'desde' tiene que ser posterior a hoy." in unescape(r.text)


def test_validate_never_runs_a_search(settings_store):
    from fastapi.testclient import TestClient

    from flytrip.web.app import create_app
    from tests.fakes import SNAPSHOT_A_B_C, StaticEngine

    engine = StaticEngine(SNAPSHOT_A_B_C)
    runs: list[object] = []
    original = engine.run

    def recording(*args, **kwargs):
        runs.append(args)
        return original(*args, **kwargs)

    engine.run = recording  # type: ignore[method-assign]
    app = create_app(engine_factory=lambda: engine, settings_store=settings_store)
    assert TestClient(app).get("/buscar/validar?" + QS).status_code == 204
    assert runs == []


def test_engine_failure_emits_error_then_done(settings_store):
    from fastapi.testclient import TestClient

    from flytrip.web.app import create_app
    from tests.fakes import SNAPSHOT_A_B_C, StaticEngine

    class Broken(StaticEngine):
        async def run(self, query, *, use_cache=True):
            raise RuntimeError("secret internal detail")
            yield

    app = create_app(engine_factory=lambda: Broken(SNAPSHOT_A_B_C), settings_store=settings_store)
    events = sse_events(TestClient(app), "/buscar/stream?" + QS)
    assert [name for name, _ in events] == ["error", "done"]
    assert "La búsqueda falló por un error inesperado. Intenta de nuevo." in events[0][1]
    assert "secret" not in events[0][1]


def test_settings_saved_in_ajustes_reach_the_running_engine_and_its_cache(tmp_path, settings_store):
    from fastapi.testclient import TestClient

    from flytrip.sources.base import PauseRegistry
    from flytrip.web.app import create_app
    from tests.engine.conftest import Clock, build_engine, google_answer, kiwi_answer
    from tests.fakes import FakeSource

    clock = Clock(datetime(2026, 11, 9, 15, 0, tzinfo=UTC))
    engine = build_engine(
        tmp_path,
        clock,
        PauseRegistry(tmp_path / "pauses.json", clock),
        kiwi=FakeSource("kiwi", kiwi_answer()),
        google=FakeSource("google", google_answer()),
        settings=settings_store.load,
    )
    client = TestClient(create_app(engine_factory=lambda: engine, settings_store=settings_store))
    assert "758 + traslado (sin configurar)" in _results(client)
    client.post(
        "/ajustes",
        data={"traslado_SCL_costo": "80", "traslado_SCL_horas": "7", "usd_por_hora": "10"},
    )
    assert "758 + 80 traslado" in _results(client)


def test_failed_origin_card_says_it_could_not_be_queried(settings_store):
    from fastapi.testclient import TestClient

    from flytrip.web.app import create_app
    from tests.fakes import SNAPSHOT_A_B_C, StaticEngine

    kept = tuple(i for i in SNAPSHOT_A_B_C.itineraries if i.origin != "EZE")
    snapshot = SNAPSHOT_A_B_C.model_copy(
        update={
            "itineraries": kept,
            "best_per_origin": {i.origin: i for i in kept} | {"EZE": None},
            "failed_origins": {"EZE": "Kiwi respondió 500"},
        }
    )
    app = create_app(engine_factory=lambda: StaticEngine(snapshot), settings_store=settings_store)
    html = unescape(_results(TestClient(app)))
    assert "No se pudo consultar este origen" in html and "Kiwi respondió 500" in html
    assert "Sin resultados para este origen" not in html


def test_unknown_separate_tickets_is_never_shown_like_a_single_ticket(client):
    html = _results(client)
    # A and C have an unknown flag, B is flagged as separate tickets.
    assert html.count("No se pudo verificar si son pasajes separados") == 2
    assert html.count("Pasajes separados: si pierdes") == 1


def _recording_app(settings_store, snapshot):
    from fastapi.testclient import TestClient

    from flytrip.web.app import create_app
    from tests.fakes import StaticEngine

    engine = StaticEngine(snapshot)
    uses: list[bool] = []
    original = engine.run

    def recording(query, *, use_cache=True):
        uses.append(use_cache)
        return original(query, use_cache=use_cache)

    engine.run = recording  # type: ignore[method-assign]
    app = create_app(engine_factory=lambda: engine, settings_store=settings_store)
    return TestClient(app), uses


def test_refrescar_bypasses_the_cache_and_plain_search_uses_it(settings_store):
    from tests.fakes import SNAPSHOT_A_B_C

    client, uses = _recording_app(settings_store, SNAPSHOT_A_B_C)
    sse_events(client, "/buscar/stream?" + QS)
    sse_events(client, "/buscar/stream?" + QS + "&refrescar=1")
    assert uses == [True, False]


def test_refresh_button_only_appears_on_cached_results(settings_store):

    from fastapi.testclient import TestClient

    from flytrip.web.app import create_app
    from tests.fakes import SNAPSHOT_A_B_C, StaticEngine

    def results(snapshot):
        app = create_app(
            engine_factory=lambda: StaticEngine(snapshot), settings_store=settings_store
        )
        return _results(TestClient(app))

    cached = SNAPSHOT_A_B_C.model_copy(update={"from_cache": True, "cache_age_minutes": 12})
    assert 'id="refresh"' in results(cached) and "Actualizar" in results(cached)
    assert "Actualizar" not in results(SNAPSHOT_A_B_C)


def test_web_validation_uses_the_today_seam(client, monkeypatch):
    monkeypatch.setenv("FLYTRIP_TODAY", "2027-06-01")
    r = client.get("/buscar/validar?" + QS)
    assert r.status_code == 422
    assert "La fecha 'desde' tiene que ser posterior a hoy." in unescape(r.text)

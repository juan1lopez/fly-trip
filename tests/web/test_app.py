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

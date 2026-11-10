from datetime import date

import pytest

from flytrip.core.query import validate_query
from tests.factories import make_query as q

TODAY = date(2026, 11, 9)


def test_valid_query_has_no_errors():
    assert validate_query(q(), TODAY) == []


@pytest.mark.parametrize(
    "kw,message",
    [
        ({"destination": "  "}, "Indica un destino."),
        ({"origins": ()}, "Elige al menos un origen."),
        ({"origins": ("MDZ", "X1")}, "Origen inválido: X1."),
        ({"depart_from": TODAY}, "La fecha 'desde' tiene que ser posterior a hoy."),
        ({"depart_to": date(2027, 2, 1)}, "La fecha 'hasta' no puede ser anterior a 'desde'."),
        ({"depart_to": date(2028, 3, 2)}, "El rango de fechas no puede superar 365 días."),
        ({"nights_max": None}, "Indica noches mínimas y máximas, o marca solo ida."),
        ({"nights_min": 0}, "Las noches tienen que estar entre 1 y 60."),
        ({"nights_min": 22}, "Las noches mínimas no pueden superar las máximas."),
        ({"adults": 10}, "Adultos: entre 1 y 9."),
    ],
)
def test_validation_messages(kw, message):
    assert message in validate_query(q(**kw), TODAY)


def test_oneway_needs_no_nights():
    query = q(nights_min=None, nights_max=None)
    assert query.trip_type == "oneway"
    assert validate_query(query, TODAY) == []


def test_cache_key_changes_with_query():
    assert q().cache_key() == q().cache_key() != q(adults=2).cache_key()


def test_today_for_validation_honours_the_test_only_env_var(monkeypatch):
    from datetime import UTC, date, datetime

    from flytrip.core.query import today_for_validation

    now = datetime(2030, 1, 5, 12, 0, tzinfo=UTC)
    monkeypatch.setenv("FLYTRIP_TODAY", "2026-11-09")
    assert today_for_validation(now) == date(2026, 11, 9)
    monkeypatch.setenv("FLYTRIP_TODAY", "not-a-date")
    assert today_for_validation(now) == date(2030, 1, 5)
    monkeypatch.delenv("FLYTRIP_TODAY")
    assert today_for_validation(now) == date(2030, 1, 5)

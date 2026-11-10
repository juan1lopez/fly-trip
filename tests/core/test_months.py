from datetime import date

import pytest

from flytrip.core.months import default_months, months_window, parse_month, validate_months

TODAY = date(2026, 11, 9)


def test_parse_month():
    assert parse_month("2027-03") == (2027, 3)


@pytest.mark.parametrize("bad", ["2027-13", "2027-00", "2027", "marzo", "2027-3-1", ""])
def test_parse_month_rejects_bad_format(bad):
    with pytest.raises(ValueError):
        parse_month(bad)


def test_default_months_crosses_the_year():
    assert default_months(TODAY) == ["2026-11", "2026-12", "2027-01"]
    assert default_months(date(2026, 12, 1)) == ["2026-12", "2027-01", "2027-02"]


def test_months_window_future_range():
    assert months_window("2027-03", "2027-05", TODAY) == (date(2027, 3, 1), date(2027, 5, 31))


def test_months_window_current_month_starts_tomorrow():
    assert months_window("2026-11", None, TODAY) == (date(2026, 11, 10), date(2026, 11, 30))


def test_months_window_leap_february():
    assert months_window("2028-02", None, TODAY)[1] == date(2028, 2, 29)


def test_validate_ok():
    assert validate_months("2027-03", "2027-06", TODAY) == []
    assert validate_months("2026-11", None, TODAY) == []


def test_validate_invalid_format():
    assert validate_months("2027-13", None, TODAY) == ["Mes inválido: 2027-13. Usa AAAA-MM."]
    assert validate_months("2027-03", "abc", TODAY) == ["Mes inválido: abc. Usa AAAA-MM."]


def test_validate_last_before_first():
    assert validate_months("2027-05", "2027-03", TODAY) == [
        "El mes 'hasta' no puede ser anterior al mes 'desde'."
    ]


def test_validate_more_than_four_months():
    assert validate_months("2027-01", "2027-05", TODAY) == ["Puedes elegir hasta 4 meses."]


def test_validate_past_month():
    assert validate_months("2026-10", None, TODAY) == ["Ese mes ya pasó: 2026-10."]


def test_month_names_are_spanish():
    from flytrip.core.months import MONTH_NAMES

    assert MONTH_NAMES[2] == "marzo" and len(MONTH_NAMES) == 12

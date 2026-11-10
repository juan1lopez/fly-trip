import calendar
from datetime import date, timedelta

MAX_MONTHS = 4
MONTH_NAMES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)


def parse_month(value: str) -> tuple[int, int]:
    """`AAAA-MM` -> (year, month). Raises ValueError on any other format."""
    year_text, sep, month_text = value.partition("-")
    if (
        not sep
        or len(year_text) != 4
        or len(month_text) != 2
        or not (year_text.isascii() and year_text.isdigit())
        or not (month_text.isascii() and month_text.isdigit())
    ):
        raise ValueError(value)
    year, month = int(year_text), int(month_text)
    if not 1 <= month <= 12:
        raise ValueError(value)
    return year, month


def _label(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


def default_months(today: date) -> list[str]:
    """The current month and the next two."""
    months: list[str] = []
    year, month = today.year, today.month
    for _ in range(3):
        months.append(_label(year, month))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def validate_months(first: str, last: str | None, today: date) -> list[str]:
    errors: list[str] = []
    parsed: list[tuple[int, int]] = []
    for value in (first, last):
        if value is None:
            continue
        try:
            parsed.append(parse_month(value))
        except ValueError:
            errors.append(f"Mes inválido: {value}. Usa AAAA-MM.")
    if errors:
        return errors
    first_ym = parsed[0]
    last_ym = parsed[-1]
    if last_ym < first_ym:
        errors.append("El mes 'hasta' no puede ser anterior al mes 'desde'.")
        return errors
    span = (last_ym[0] - first_ym[0]) * 12 + last_ym[1] - first_ym[1] + 1
    if span > MAX_MONTHS:
        errors.append(f"Puedes elegir hasta {MAX_MONTHS} meses.")
    if first_ym < (today.year, today.month):
        errors.append(f"Ese mes ya pasó: {first}.")
    elif date(*first_ym, calendar.monthrange(*first_ym)[1]) <= today:
        errors.append(f"Ese mes ya terminó: {first}.")
    return errors


def months_window(first: str, last: str | None, today: date) -> tuple[date, date]:
    """(max(first day, tomorrow), last day of the last month). Months must be valid."""
    year, month = parse_month(first)
    end_year, end_month = parse_month(last) if last is not None else (year, month)
    start = max(date(year, month, 1), today + timedelta(days=1))
    end = date(end_year, end_month, calendar.monthrange(end_year, end_month)[1])
    return start, end

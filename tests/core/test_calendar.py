from datetime import date, timedelta
from decimal import Decimal

from flytrip.core.calendar import CalendarDay, build_calendar, cheap_days, month_grid
from tests.factories import T


def test_build_calendar_takes_minimum_with_transfer_sorted_by_day():
    entries = [
        ("SCL", date(2027, 3, 10), Decimal("900")),
        ("EZE", date(2027, 3, 10), Decimal("800")),
        ("MDZ", date(2027, 3, 9), Decimal("1000")),
    ]
    transfers = {"SCL": T("80", "7"), "EZE": T("200", "2"), "MDZ": None}
    days = build_calendar(entries, transfers)
    assert days == [
        CalendarDay(day=date(2027, 3, 9), price_usd=Decimal("1000"), origin="MDZ"),
        CalendarDay(day=date(2027, 3, 10), price_usd=Decimal("980"), origin="SCL"),
    ]


def test_build_calendar_unknown_origin_counts_no_transfer():
    days = build_calendar([("XXX", date(2027, 3, 1), Decimal("50"))], {})
    assert days[0].price_usd == Decimal("50")


def _days(prices: list[int]) -> list[CalendarDay]:
    return [
        CalendarDay(day=date(2027, 3, 1) + timedelta(days=i), price_usd=Decimal(p), origin="MDZ")
        for i, p in enumerate(prices)
    ]


def test_cheap_days_is_the_cheapest_tenth():
    days = _days(list(range(100, 200, 5)) + list(range(300, 320)))  # 40 days
    assert cheap_days(days) == {date(2027, 3, 1) + timedelta(days=i) for i in range(4)}


def test_cheap_days_returns_at_least_one():
    assert cheap_days(_days([500, 400, 600])) == {date(2027, 3, 2)}
    assert cheap_days([]) == set()


def test_month_grid_starts_on_monday():
    grid = month_grid(2027, 3)
    assert grid[0][0] == date(2027, 3, 1)  # March 1st 2027 is a Monday
    assert all(len(week) == 7 for week in grid)
    assert sum(d is not None for week in grid for d in week) == 31
    assert month_grid(2027, 4)[0][:3] == [None, None, None]  # April 1st is a Thursday

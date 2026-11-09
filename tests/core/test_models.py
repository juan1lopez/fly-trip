from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from flytrip.core.query import today_in_mendoza
from tests.factories import T, make_itinerary


def test_total_and_travel_hours_with_transfer():
    it = make_itinerary(
        origin="SCL", price="758", out_minutes=780, in_minutes=780, transfer=T("80", "7")
    )
    assert it.total_from_home_usd == Decimal("838")
    assert it.travel_hours == Decimal("40")


def test_oneway_counts_transfer_once():
    it = make_itinerary(trip_type="oneway", out_minutes=600, transfer=T("0", "3"))
    assert it.travel_hours == Decimal("13")


def test_best_offer_is_cheapest():
    it = make_itinerary(offers=[("kiwi", "800", "u1"), ("google", "700", "u2")])
    assert it.best_offer.source == "google"
    assert it.price_usd == Decimal("700")


def test_transfer_rejects_negative():
    with pytest.raises(ValidationError):
        T("-1", "2")


def test_today_in_mendoza_is_utc_minus_3():
    assert today_in_mendoza(datetime(2026, 11, 10, 2, 30, tzinfo=UTC)) == date(2026, 11, 9)

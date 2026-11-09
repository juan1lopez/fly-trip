from flytrip.core.legs import build_leg, itinerary_id, normalize_flight_number
from flytrip.core.models import Layover
from tests.factories import seg


def test_normalize_flight_number():
    assert normalize_flight_number("IB", "IB6830") == "6830"
    assert normalize_flight_number("IB", "06830") == "6830"
    assert normalize_flight_number("H2", "H2 123") == "123"
    assert normalize_flight_number("JA", "7104") == "7104"


def test_build_leg_computes_layovers():
    leg = build_leg(
        [
            seg("JA", "7104", "MDZ", "SCL", "2027-03-10T06:00", "2027-03-10T07:00"),
            seg("IB", "6830", "SCL", "MAD", "2027-03-10T23:50", "2027-03-11T16:40"),
        ],
        1830,
    )
    assert leg.stops == 1 and leg.duration_minutes == 1830
    assert leg.layovers[0] == Layover(
        airport="SCL", minutes=1010, overnight=False, airport_change=False
    )


def test_overnight_and_airport_change():
    leg = build_leg(
        [
            seg("AR", "1405", "MDZ", "AEP", "2027-03-10T20:00", "2027-03-10T22:00"),
            seg("AR", "1132", "EZE", "MAD", "2027-03-11T08:00", "2027-03-12T01:00"),
        ],
        1740,
    )
    assert leg.layovers[0] == Layover(
        airport="AEP", minutes=600, overnight=True, airport_change=True
    )


def test_itinerary_id_is_stable_and_order_sensitive():
    a = build_leg([seg("IB", "6830", "SCL", "MAD", "2027-03-19T00:50", "2027-03-19T17:30")], 760)
    b = build_leg([seg("IB", "6831", "MAD", "SCL", "2027-04-04T23:55", "2027-04-05T08:45")], 750)
    assert itinerary_id(a, b) == itinerary_id(a, b) != itinerary_id(b, a)
    assert len(itinerary_id(a, None)) == 16

from datetime import date, timedelta

from flytrip.core.candidates import DatePair, select_google_candidates
from tests.factories import itin_on, make_itinerary
from tests.factories import make_query as q


def test_round_robin_respects_budget_for_return_trips():
    kiwi = [
        itin_on("SCL", "2027-03-19", "2027-04-04", 758),
        itin_on("SCL", "2027-03-11", "2027-03-31", 763),
        itin_on("MDZ", "2027-03-10", "2027-03-25", 934),
        itin_on("MDZ", "2027-03-09", "2027-03-24", 949),
        itin_on("EZE", "2027-03-07", "2027-03-26", 1021),
        itin_on("EZE", "2027-04-18", "2027-05-05", 1038),
        itin_on("SCL", "2027-03-08", "2027-03-24", 763),
    ]
    pairs = select_google_candidates(kiwi, q(), fetch_budget=12)
    assert [(p.origin, p.depart.isoformat()) for p in pairs] == [
        ("MDZ", "2027-03-10"),
        ("SCL", "2027-03-19"),
        ("EZE", "2027-03-07"),
        ("MDZ", "2027-03-09"),
        ("SCL", "2027-03-11"),
        ("EZE", "2027-04-18"),
    ]


def test_fallback_dates_when_origin_has_no_kiwi_results():
    pairs = select_google_candidates([], q(origins=("EZE",)), fetch_budget=12)
    assert [p.depart.isoformat() for p in pairs] == [
        "2027-03-19",
        "2027-04-06",
        "2027-04-25",
        "2027-05-13",
    ]
    assert all(p.return_date == p.depart + timedelta(days=14) for p in pairs)


def test_selection_stops_at_the_first_pair_that_does_not_fit():
    # Mixed costs only to tell stopping apart from skipping: EZE's pair costs 1 fetch.
    kiwi = [
        itin_on("MDZ", "2027-03-10", "2027-03-25", 934),
        itin_on("SCL", "2027-03-19", "2027-04-04", 758),
        make_itinerary(id="OW", origin="EZE", trip_type="oneway"),
    ]
    pairs = select_google_candidates(kiwi, q(), fetch_budget=3)
    assert [p.origin for p in pairs] == ["MDZ"]


def test_no_fallback_for_city_names():
    assert select_google_candidates([], q(destination="Madrid"), fetch_budget=12) == []


def test_city_search_confirms_the_real_airport_once_per_date_pair():
    kiwi = [
        itin_on("SCL", "2027-03-19", "2027-04-04", 800),
        itin_on("SCL", "2027-03-19", "2027-04-04", 758),
    ]
    pairs = select_google_candidates(kiwi, q(destination="Madrid", origins=("SCL",)))
    assert pairs == [DatePair("SCL", "MAD", date(2027, 3, 19), date(2027, 4, 4))]
    assert pairs[0].cost == 2


def test_one_way_pairs_cost_one_fetch_each():
    pairs = select_google_candidates([], q(nights_min=None, nights_max=None), fetch_budget=12)
    assert len(pairs) == 12 and {p.return_date for p in pairs} == {None}
    assert {p.cost for p in pairs} == {1}
    assert [p.origin for p in pairs[:3]] == ["MDZ", "SCL", "EZE"]

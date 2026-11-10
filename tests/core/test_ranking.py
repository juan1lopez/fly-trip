from decimal import Decimal

from flytrip.core.ranking import (
    apply_transfers,
    best_balance,
    best_per_origin,
    mark_separate_tickets,
    merge_duplicates,
    sort_by_total,
)
from tests.factories import T, make_itinerary


def test_sort_best_per_origin_and_balance():
    a = make_itinerary(
        id="A", origin="SCL", price="758", out_minutes=780, in_minutes=780, transfer=T("80", "7")
    )
    b = make_itinerary(id="B", origin="MDZ", price="934", out_minutes=900, in_minutes=960)
    c = make_itinerary(
        id="C", origin="EZE", price="1021", out_minutes=750, in_minutes=780, transfer=T("200", "2")
    )
    ranked = sort_by_total([c, b, a])
    assert [i.id for i in ranked] == ["A", "B", "C"]
    assert best_per_origin(ranked, ["MDZ", "SCL", "EZE", "AEP"]) == {
        "MDZ": b,
        "SCL": a,
        "EZE": c,
        "AEP": None,
    }
    best10 = best_balance(ranked, Decimal("10"))
    best20 = best_balance(ranked, Decimal("20"))
    assert best10 is not None and best10.id == "A"  # 838+400=1238 < 934+310=1244
    assert best20 is not None and best20.id == "B"  # 934+620=1554 < 838+800=1638
    assert best_balance([], Decimal("10")) is None


def test_merge_keeps_both_links_cheapest_first():
    k = make_itinerary(id="X", offers=[("kiwi", "763", "https://kiwi.com/u/1")])
    g = make_itinerary(
        id="X",
        offers=[("google", "770", "https://www.google.com/travel/flights?q=x")],
        separate_tickets=False,
    )
    [m] = merge_duplicates([g, k])
    assert [o.source for o in m.offers] == ["kiwi", "google"]
    assert m.price_usd == Decimal("763") and m.separate_tickets is False


def test_merge_dedups_offers_and_separate_tickets_true_wins():
    a = make_itinerary(id="X", separate_tickets=False)
    b = make_itinerary(id="X", separate_tickets=True)
    c = make_itinerary(id="Y")
    merged = merge_duplicates([a, b, c])
    assert [i.id for i in merged] == ["X", "Y"]
    assert len(merged[0].offers) == 1
    assert merged[0].separate_tickets is True
    assert merged[1].separate_tickets is None


def test_mark_separate_tickets_from_two_modes():
    x, y = make_itinerary(id="X"), make_itinerary(id="Y")
    marked = {
        i.id: i.separate_tickets for i in mark_separate_tickets(all_mode=[x, y], protected_mode=[y])
    }
    assert marked == {"X": True, "Y": False}


def test_apply_transfers_by_origin():
    [scl] = apply_transfers(
        [make_itinerary(origin="SCL", price="758")], {"SCL": T("80", "7"), "EZE": None}
    )
    [mdz] = apply_transfers([make_itinerary(origin="MDZ", price="934")], {"SCL": T("80", "7")})
    assert scl.total_from_home_usd == Decimal("838")
    assert mdz.transfer is None and mdz.total_from_home_usd == Decimal("934")

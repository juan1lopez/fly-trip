from datetime import date

from flytrip.engine.doctor import SourceHealth, check_result_shape, run_doctor
from flytrip.sources.base import PauseRegistry, SourceResult
from tests.factories import CLOCK, make_itinerary
from tests.fakes import FakeSource


def test_shape_ok():
    h = check_result_shape(
        SourceResult(source="kiwi", status="ok", itineraries=(make_itinerary(),), latency_ms=2300)
    )
    assert h.ok and h.detail == "OK: 1 itinerarios en 2,3 s"


def test_shape_empty_is_broken():
    result = SourceResult(source="kiwi", status="ok")
    assert check_result_shape(result).detail == "Rota: 0 itinerarios"


def test_shape_passes_source_detail():
    r = SourceResult(
        source="google", status="error", detail="Google cambió el formato de la página"
    )
    assert check_result_shape(r) == SourceHealth(
        "google", False, "Rota: Google cambió el formato de la página", 0
    )


def test_shape_rejects_non_https_url():
    bad = make_itinerary()
    offer = bad.offers[0].model_copy(update={"booking_url": "http://example.com"})
    bad = bad.model_copy(update={"offers": (offer,)})
    result = SourceResult(source="kiwi", status="ok", itineraries=(bad,))
    assert not check_result_shape(result).ok


def test_shape_rejects_zero_price():
    bad = make_itinerary()
    offer = bad.offers[0].model_copy(update={"price_usd": 0})
    bad = bad.model_copy(update={"offers": (offer,)})
    result = SourceResult(source="kiwi", status="ok", itineraries=(bad,))
    assert not check_result_shape(result).ok


async def test_run_doctor_builds_requests_and_never_raises(tmp_path):
    kiwi = FakeSource(
        "kiwi", lambda r: SourceResult(source="kiwi", status="ok", itineraries=(make_itinerary(),))
    )
    google = FakeSource("google", lambda r: RuntimeError("boom"))
    skiplagged = FakeSource(
        "skiplagged",
        lambda r: SourceResult(source="skiplagged", status="ok", itineraries=(make_itinerary(),)),
    )
    health = await run_doctor(
        kiwi,
        google,
        skiplagged,
        today=date(2026, 11, 9),
        pauses=PauseRegistry(tmp_path / "p.json", CLOCK),
        clock=CLOCK,
    )
    assert [(h.source, h.ok) for h in health] == [
        ("kiwi", True),
        ("google", False),
        ("skiplagged", True),
    ]
    k = kiwi.calls[0]
    assert (k.origin, k.destination) == ("SCL", "MAD")
    assert (k.depart_from, k.depart_to) == (date(2026, 12, 9), date(2026, 12, 23))
    assert k.nights_min == k.nights_max == 14
    g = google.calls[0]
    assert g.depart_from == g.depart_to == date(2026, 12, 9)
    s = skiplagged.calls[0]
    assert (s.origin, s.destination) == ("SCL", "MAD")
    assert s.depart_from == s.depart_to == date(2026, 12, 9)
    assert s.nights_min == s.nights_max == 14
    assert s.allow_separate_tickets is False


async def test_run_doctor_skiplagged_failure_is_a_broken_health(tmp_path):
    ok = SourceResult(source="kiwi", status="ok", itineraries=(make_itinerary(),))
    health = await run_doctor(
        FakeSource("kiwi", lambda r: ok),
        FakeSource("google", lambda r: ok),
        FakeSource("skiplagged", lambda r: RuntimeError("boom")),
        today=date(2026, 11, 9),
        pauses=PauseRegistry(tmp_path / "p.json", CLOCK),
        clock=CLOCK,
    )
    assert health[2].source == "skiplagged" and not health[2].ok
    assert health[2].detail.startswith("Rota:")

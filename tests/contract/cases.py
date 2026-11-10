from dataclasses import dataclass
from datetime import date

from flytrip.sources.base import Source, SourceBlocked, SourceRequest, SourceResult
from tests.factories import make_itinerary
from tests.fakes import FakeSource

REQ = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 1),
    depart_to=date(2027, 5, 31),
    nights_min=14,
    nights_max=21,
    adults=1,
    allow_separate_tickets=True,
)


@dataclass(frozen=True)
class ContractCase:
    id: str
    source: Source
    request: SourceRequest
    expected_status: str


def _ok(request: SourceRequest) -> SourceResult:
    itinerary = make_itinerary(offers=[("kiwi", "758", "https://kiwi.example/x")])
    return SourceResult(source="kiwi", status="ok", itineraries=(itinerary,), fetches=1)


CONTRACT_CASES: list[ContractCase] = [
    ContractCase("fake-ok", FakeSource("kiwi", _ok), REQ, "ok"),
    ContractCase("fake-error", FakeSource("kiwi", lambda r: RuntimeError("boom")), REQ, "error"),
    ContractCase(
        "fake-blocked", FakeSource("google", lambda r: SourceBlocked("429")), REQ, "paused"
    ),
    ContractCase(
        "fake-slow",
        FakeSource("kiwi", lambda r: SourceResult(source="kiwi", status="ok"), delay_s=5),
        REQ,
        "timeout",
    ),
]

from tests.contract.cases_google import GOOGLE_CASES  # noqa: E402
from tests.contract.cases_kiwi import KIWI_CASES  # noqa: E402
from tests.contract.cases_skiplagged import SKIPLAGGED_CASES  # noqa: E402

CONTRACT_CASES += KIWI_CASES
CONTRACT_CASES += GOOGLE_CASES
CONTRACT_CASES += SKIPLAGGED_CASES

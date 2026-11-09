from datetime import date

from fli.search import SearchHTTPError
from fli.search.flights import SearchParseError

from flytrip.sources.base import SourceRequest
from flytrip.sources.google_flights import GoogleFlightsSource
from tests.contract.cases import REQ, ContractCase
from tests.factories import CLOCK
from tests.fakes import FakeFli, load_fli

_EXACT = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 19),
    depart_to=date(2027, 3, 19),
    nights_min=16,
    nights_max=16,
    adults=1,
    allow_separate_tickets=True,
)
_ONEWAY = SourceRequest(
    origin="EZE",
    destination="MAD",
    depart_from=date(2027, 3, 7),
    depart_to=date(2027, 3, 7),
    nights_min=None,
    nights_max=None,
    adults=1,
    allow_separate_tickets=True,
)


def _source(fake: FakeFli) -> GoogleFlightsSource:
    return GoogleFlightsSource(fake, clock=CLOCK)


GOOGLE_CASES: list[ContractCase] = [
    ContractCase("google-rt-ok", _source(FakeFli(load_fli("madrid_scl_rt.json"))), _EXACT, "ok"),
    ContractCase(
        "google-oneway-ok", _source(FakeFli(load_fli("madrid_eze_oneway.json"))), _ONEWAY, "ok"
    ),
    ContractCase(
        "google-wrong-currency",
        _source(FakeFli(load_fli("wrong_currency.json"))),
        _ONEWAY,
        "error",
    ),
    ContractCase(
        "google-429",
        _source(FakeFli(raises=SearchHTTPError("x", status_code=429))),
        _EXACT,
        "paused",
    ),
    ContractCase(
        "google-malformed-response",
        _source(FakeFli(raises=SearchParseError("shape changed"))),
        _EXACT,
        "error",
    ),
    ContractCase("google-window-is-error", _source(FakeFli(None)), REQ, "error"),
]

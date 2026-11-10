from datetime import date

import httpx
import respx

from flytrip.sources.base import SourceRequest
from flytrip.sources.skiplagged import SKIPLAGGED_URL, SkiplaggedSource
from tests.contract.cases import ContractCase
from tests.factories import CLOCK, fixture

REQUEST = SourceRequest(
    origin="SCL",
    destination="MAD",
    depart_from=date(2027, 3, 19),
    depart_to=date(2027, 3, 19),
    nights_min=16,
    nights_max=16,
    adults=1,
    allow_separate_tickets=True,
)


class _MockedSkiplagged:
    """SkiplaggedSource cuyo cliente httpx responde con un fixture, sin red."""

    name = "skiplagged"

    def __init__(self, fixture_name: str, status_code: int = 200) -> None:
        self._body = fixture("skiplagged", fixture_name)
        self._status = status_code

    async def search(self, request: SourceRequest):  # type: ignore[no-untyped-def]
        with respx.mock(assert_all_called=False) as router:
            router.post(SKIPLAGGED_URL).mock(
                return_value=httpx.Response(self._status, text=self._body)
            )
            async with httpx.AsyncClient() as client:
                return await SkiplaggedSource(client, clock=CLOCK).search(request)


SKIPLAGGED_CASES: list[ContractCase] = [
    ContractCase("skiplagged-madrid-scl-rt", _MockedSkiplagged("madrid_scl_rt.sse"), REQUEST, "ok"),
    ContractCase("skiplagged-synthetic-rt", _MockedSkiplagged("synthetic_rt.sse"), REQUEST, "ok"),
    ContractCase("skiplagged-hidden-city", _MockedSkiplagged("hidden_city.sse"), REQUEST, "ok"),
    ContractCase("skiplagged-empty", _MockedSkiplagged("empty.sse"), REQUEST, "ok"),
    ContractCase("skiplagged-tool-error", _MockedSkiplagged("tool_error.sse"), REQUEST, "error"),
    ContractCase("skiplagged-malformed", _MockedSkiplagged("malformed.sse"), REQUEST, "error"),
    ContractCase(
        "skiplagged-blocked", _MockedSkiplagged("empty.sse", status_code=429), REQUEST, "paused"
    ),
]

from datetime import date

import httpx
import respx

from flytrip.sources.base import SourceRequest
from flytrip.sources.kiwi import KIWI_URL, KiwiSource
from tests.contract.cases import ContractCase
from tests.factories import CLOCK, fixture

_ORIGINS = {
    "madrid_scl_return": "SCL",
    "madrid_mdz_return_all": "MDZ",
    "madrid_mdz_return_protected": "MDZ",
    "madrid_eze_return": "EZE",
    "empty": "SCL",
}


class _MockedKiwi:
    """KiwiSource cuyo cliente httpx responde con un fixture, sin red."""

    name = "kiwi"

    def __init__(self, fixture_name: str | None = None, body: str | None = None) -> None:
        self._body = body if body is not None else fixture("kiwi", str(fixture_name))

    async def search(self, request: SourceRequest):  # type: ignore[no-untyped-def]
        with respx.mock(assert_all_called=False) as router:
            router.post(KIWI_URL).mock(return_value=httpx.Response(200, text=self._body))
            async with httpx.AsyncClient() as client:
                return await KiwiSource(client, clock=CLOCK).search(request)


def _request(origin: str) -> SourceRequest:
    return SourceRequest(
        origin=origin,
        destination="MAD",
        depart_from=date(2027, 3, 1),
        depart_to=date(2027, 3, 10),
        nights_min=14,
        nights_max=21,
        adults=1,
        allow_separate_tickets=True,
    )


KIWI_CASES: list[ContractCase] = [
    ContractCase(f"kiwi-{name}", _MockedKiwi(f"{name}.sse"), _request(origin), "ok")
    for name, origin in _ORIGINS.items()
]

GARBLED_SSE = "event: message\ndata: {this is not json\n\ndata: [1, 2\n\n<html>captcha</html>\n"

KIWI_CASES.append(
    ContractCase("kiwi-garbled-sse", _MockedKiwi(body=GARBLED_SSE), _request("SCL"), "error")
)

import pytest

from flytrip.sources.base import PauseRegistry, run_safely
from tests.contract.cases import CONTRACT_CASES
from tests.factories import CLOCK


@pytest.mark.parametrize("case", CONTRACT_CASES, ids=lambda c: c.id)
async def test_source_contract(case, tmp_path):
    result = await run_safely(
        case.source,
        case.request,
        timeout_s=2,
        pauses=PauseRegistry(tmp_path / "p.json", CLOCK),
        clock=CLOCK,
    )
    assert result.status == case.expected_status
    for it in result.itineraries:
        assert it.offers
        assert all(o.source == case.source.name for o in it.offers)
        assert all(o.price_usd > 0 and o.booking_url.startswith("https://") for o in it.offers)
        for leg in filter(None, (it.outbound, it.inbound)):
            assert all(len(s.from_airport) == 3 and s.from_airport.isupper() for s in leg.segments)

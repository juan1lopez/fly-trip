from datetime import date

import pytest

from flytrip.devtools.record_google import record_google
from tests.fakes import FakeFli


def test_empty_response_raises_and_keeps_existing_fixture(tmp_path):
    existing = tmp_path / "madrid_scl_rt.json"
    existing.write_text('["keep"]', encoding="utf-8")
    with pytest.raises(RuntimeError, match="no se sobrescribe el fixture"):
        record_google(
            "madrid_scl_rt", "SCL", "MAD", date(2027, 3, 19), 16, 1, tmp_path, client=FakeFli(None)
        )
    assert existing.read_text(encoding="utf-8") == '["keep"]'

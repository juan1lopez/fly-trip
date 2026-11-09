from decimal import Decimal

import pytest
from pydantic import ValidationError

from flytrip.core.models import TransferCost
from flytrip.engine.settings import Settings, SettingsStore
from tests.factories import T


def test_defaults_when_missing(tmp_path):
    s = SettingsStore(tmp_path / "settings.json").load()
    assert s.default_origins == ("MDZ", "SCL", "EZE") and s.usd_per_hour == Decimal("10")
    assert s.transfers == {"SCL": None, "EZE": None} and s.adults == 1


def test_roundtrip(tmp_path):
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(transfers={"SCL": T("80", "7"), "EZE": None}))
    assert store.load().transfers["SCL"] == T("80", "7")
    assert store.load().usd_per_hour == Decimal("10")


def test_invalid_file_falls_back_to_defaults(tmp_path, caplog):
    (tmp_path / "settings.json").write_text("{nope", encoding="utf-8")
    with caplog.at_level("WARNING", logger="flytrip.settings"):
        assert SettingsStore(tmp_path / "settings.json").load() == Settings()
    assert caplog.records


def test_negative_transfer_is_rejected():
    with pytest.raises(ValidationError):
        TransferCost(cost_usd_roundtrip=Decimal("-1"), hours_one_way=Decimal("1"))


def test_paths_create_dirs(tmp_path, monkeypatch):
    from flytrip.engine.paths import data_dir, home_dir, logs_dir

    monkeypatch.setenv("FLYTRIP_HOME", str(tmp_path))
    assert home_dir() == tmp_path
    assert data_dir(tmp_path) == tmp_path / ".flytrip" and (tmp_path / ".flytrip").is_dir()
    assert logs_dir(tmp_path) == tmp_path / "logs" and (tmp_path / "logs").is_dir()

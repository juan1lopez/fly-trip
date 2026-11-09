import logging
import os
import tempfile
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ValidationError

from flytrip.core.models import TransferCost

log = logging.getLogger("flytrip.settings")


class Settings(BaseModel):
    default_origins: tuple[str, ...] = ("MDZ", "SCL", "EZE")
    home_city: str = "Mendoza"
    transfers: dict[str, TransferCost | None] = {"SCL": None, "EZE": None}
    adults: int = 1
    usd_per_hour: Decimal = Decimal("10")
    allow_separate_tickets: bool = True


class SettingsStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def load(self) -> Settings:
        if not self._path.exists():
            return Settings()
        try:
            return Settings.model_validate_json(self._path.read_text(encoding="utf-8"))
        except (ValidationError, OSError, ValueError) as exc:
            log.warning(
                "Ajustes inválidos en %s, se usan los valores por defecto: %s", self._path, exc
            )
            return Settings()

    def save(self, settings: Settings) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=self._path.parent, prefix=".settings-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(settings.model_dump_json(indent=2))
            os.replace(tmp_name, self._path)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise

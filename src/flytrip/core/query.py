import hashlib
import json
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict

MENDOZA_TZ = ZoneInfo("America/Argentina/Mendoza")


def today_in_mendoza(now_utc: datetime) -> date:
    return now_utc.astimezone(MENDOZA_TZ).date()


class SearchQuery(BaseModel):
    """Sin restricciones de rango: solo `validate_query` valida."""

    model_config = ConfigDict(frozen=True)

    destination: str
    origins: tuple[str, ...]
    depart_from: date
    depart_to: date
    nights_min: int | None
    nights_max: int | None
    adults: int = 1
    allow_separate_tickets: bool = True

    @property
    def trip_type(self) -> Literal["oneway", "return"]:
        if self.nights_min is None and self.nights_max is None:
            return "oneway"
        return "return"

    def cache_key(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()


def validate_query(query: SearchQuery, today: date, max_window_days: int = 365) -> list[str]:
    errors: list[str] = []
    if not query.destination.strip():
        errors.append("Indica un destino.")
    if not query.origins:
        errors.append("Elige al menos un origen.")
    for origin in query.origins:
        if not (len(origin) == 3 and origin.isascii() and origin.isalpha()):
            errors.append(f"Origen inválido: {origin}.")
    if query.depart_from <= today:
        errors.append("La fecha 'desde' tiene que ser posterior a hoy.")
    if query.depart_to < query.depart_from:
        errors.append("La fecha 'hasta' no puede ser anterior a 'desde'.")
    elif (query.depart_to - query.depart_from).days > max_window_days:
        errors.append(f"El rango de fechas no puede superar {max_window_days} días.")
    lo, hi = query.nights_min, query.nights_max
    if (lo is None) != (hi is None):
        errors.append("Indica noches mínimas y máximas, o marca solo ida.")
    elif lo is not None and hi is not None:
        if not (1 <= lo <= 60 and 1 <= hi <= 60):
            errors.append("Las noches tienen que estar entre 1 y 60.")
        if lo > hi:
            errors.append("Las noches mínimas no pueden superar las máximas.")
    if not 1 <= query.adults <= 9:
        errors.append("Adultos: entre 1 y 9.")
    return errors

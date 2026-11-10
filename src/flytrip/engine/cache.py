"""SQLite cache of finished searches; a broken cache never breaks a search."""

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

log = logging.getLogger("flytrip.cache")

_SCHEMA = "CREATE TABLE IF NOT EXISTS searches (key TEXT PRIMARY KEY, stored_at TEXT, payload TEXT)"


def _stamp(moment: datetime) -> str:
    # One UTC format for every row, so `stored_at` values compare correctly as text.
    return moment.astimezone(UTC).isoformat(timespec="seconds")


class SearchCache:
    def __init__(self, path: Path, clock: Callable[[], datetime], ttl_minutes: int = 30) -> None:
        self._path = path
        self._clock = clock
        self._ttl = timedelta(minutes=ttl_minutes)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._path)) as conn:
            conn.execute(_SCHEMA)
            with conn:  # commits on success, rolls back on error
                yield conn

    def get(self, key: str) -> tuple[str, int] | None:
        """The stored JSON and its age in whole minutes, or None if missing or expired."""
        try:
            with self._db() as conn:
                row = conn.execute(
                    "SELECT stored_at, payload FROM searches WHERE key = ?", (key,)
                ).fetchone()
            if row is None:
                return None
            age = self._clock() - datetime.fromisoformat(row[0])
        except (sqlite3.Error, OSError, ValueError, TypeError) as exc:
            log.warning("No se pudo leer la caché %s: %s", self._path, exc)
            return None
        if age >= self._ttl:
            return None
        return str(row[1]), max(0, int(age.total_seconds() // 60))

    def put(self, key: str, payload_json: str) -> None:
        now = self._clock()
        try:
            with self._db() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO searches (key, stored_at, payload) VALUES (?, ?, ?)",
                    (key, _stamp(now), payload_json),
                )
                conn.execute(
                    "DELETE FROM searches WHERE stored_at <= ?", (_stamp(now - self._ttl),)
                )
        except (sqlite3.Error, OSError) as exc:
            log.warning("No se pudo guardar la caché %s: %s", self._path, exc)

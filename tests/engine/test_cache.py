import sqlite3
from contextlib import closing

from flytrip.engine.cache import SearchCache


def test_put_then_get_reports_age_in_minutes(tmp_path, clock):
    cache = SearchCache(tmp_path / "cache.sqlite", clock)
    assert cache.get("k") is None
    cache.put("k", '{"a": 1}')
    clock.advance(minutes=10, seconds=30)
    assert cache.get("k") == ('{"a": 1}', 10)


def test_entries_expire_after_ttl(tmp_path, clock):
    cache = SearchCache(tmp_path / "cache.sqlite", clock, ttl_minutes=30)
    cache.put("k", "x")
    clock.advance(minutes=29, seconds=59)
    assert cache.get("k") == ("x", 29)
    clock.advance(seconds=1)
    assert cache.get("k") is None


def test_put_replaces_entry_and_persists_in_sqlite_table(tmp_path, clock):
    path = tmp_path / "sub" / "cache.sqlite"
    SearchCache(path, clock).put("k", "old")
    clock.advance(minutes=5)
    SearchCache(path, clock).put("k", "new")
    assert SearchCache(path, clock).get("k") == ("new", 0)
    with closing(sqlite3.connect(path)) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(searches)")]
    assert columns == ["key", "stored_at", "payload"]


def test_put_purges_expired_entries(tmp_path, clock):
    path = tmp_path / "cache.sqlite"
    cache = SearchCache(path, clock)
    cache.put("old", "x")
    clock.advance(minutes=31)
    cache.put("new", "y")
    with closing(sqlite3.connect(path)) as conn:
        keys = [row[0] for row in conn.execute("SELECT key FROM searches")]
    assert keys == ["new"]


def test_broken_cache_file_is_a_miss_and_never_raises(tmp_path, clock):
    path = tmp_path / "cache.sqlite"
    path.write_bytes(b"this is not a database")
    cache = SearchCache(path, clock)
    assert cache.get("k") is None
    cache.put("k", "x")
    assert cache.get("k") is None

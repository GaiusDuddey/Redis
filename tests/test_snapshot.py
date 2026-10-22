import pytest

from miniredis.persistence.snapshot import SnapshotError, load, save
from miniredis.store import Store

from .helpers import FakeClock, run, state


def fill(store):
    run(store, "SET", "str", "hello", "EX", "1000")
    run(store, "SET", "plain", "x")
    run(store, "RPUSH", "list", "a", "b", "c")
    run(store, "HSET", "hash", "f1", "v1", "f2", "v2")
    run(store, "SADD", "set", "x", "y", "z")
    run(store, "ZADD", "zset", "1.5", "a", "-2", "b", "0.1", "c")
    run(store, "EXPIRE", "list", "500")


def test_roundtrip_all_types_and_ttl(tmp_path):
    clock = FakeClock()
    a = Store(clock_ms=clock)
    fill(a)
    path = str(tmp_path / "dump.mrdb")
    assert save(a, path) == 6
    b = Store(clock_ms=clock)
    assert load(b, path, clock()) == 6
    assert state(b) == state(a)
    assert state(b)[b"str"][1] == clock() + 1_000_000  # absolute deadline preserved


def test_save_replaces_old_file_and_leaves_no_temp(tmp_path):
    s = Store()
    run(s, "SET", "a", "1")
    path = tmp_path / "dump.mrdb"
    save(s, str(path))
    run(s, "SET", "b", "2")
    save(s, str(path))
    assert sorted(p.name for p in tmp_path.iterdir()) == ["dump.mrdb"]
    t = Store()
    load(t, str(path), t.now_ms())
    assert set(state(t)) == {b"a", b"b"}


def test_load_rejects_corrupt_files(tmp_path):
    s = Store()
    run(s, "SET", "k", "value")
    run(s, "RPUSH", "l", "a", "b")
    path = tmp_path / "dump.mrdb"
    save(s, str(path))
    good = path.read_bytes()
    flipped = bytearray(good)
    flipped[len(good) // 2] ^= 0xFF
    cases = [bytes(flipped), good[:-7], b"NOPE" + good[4:], b""]
    for blob in cases:
        bad = tmp_path / "bad.mrdb"
        bad.write_bytes(blob)
        with pytest.raises(SnapshotError):
            load(Store(), str(bad), 0)


def test_expired_keys_not_saved(tmp_path):
    clock = FakeClock()
    s = Store(clock_ms=clock)
    run(s, "SET", "gone", "1", "PX", "100")
    run(s, "SET", "kept", "1")
    clock.advance(500)
    path = str(tmp_path / "dump.mrdb")
    assert save(s, path) == 1
    t = Store(clock_ms=clock)
    load(t, path, clock())
    assert set(state(t)) == {b"kept"}


def test_scores_roundtrip_exactly(tmp_path):
    s = Store()
    run(s, "ZADD", "z", repr(0.1 + 0.2), "a", "inf", "b", "-inf", "c", "1e300", "d")
    path = str(tmp_path / "dump.mrdb")
    save(s, path)
    t = Store()
    load(t, path, t.now_ms())
    assert state(t) == state(s)

import os

import pytest

from miniredis.persistence.aof import AofError, AofWriter, replay, translate
from miniredis.resp import encode_command
from miniredis.store import Store

from .helpers import FakeClock, run, state


def logged(store, aof, *args):
    """Run a command and log it exactly the way the server does."""
    args = [a.encode() if isinstance(a, str) else a for a in args]
    reply = run(store, *args)
    for entry in translate(store, args, reply):
        aof.append(entry)
    return reply


def recover(path, clock=None):
    store = Store(clock_ms=clock) if clock else Store()
    count, cut = replay(str(path), store)
    return store, count, cut


def test_encode_command():
    assert (
        encode_command([b"SET", b"k", b"v"])
        == b"*3\r\n$3\r\nSET\r\n$1\r\nk\r\n$1\r\nv\r\n"
    )


def test_translate_set_ex_becomes_absolute_pexpireat():
    clock = FakeClock()
    s = Store(clock_ms=clock)
    args = [b"SET", b"k", b"v", b"EX", b"10"]
    reply = run(s, *args)
    assert translate(s, args, reply) == [
        [b"SET", b"k", b"v"],
        [b"PEXPIREAT", b"k", str(clock() + 10_000).encode()],
    ]


def test_translate_set_keepttl_and_plain_set():
    s = Store()
    run(s, "SET", "k", "v", "EX", "10")
    args = [b"SET", b"k", b"v2", b"KEEPTTL"]
    assert translate(s, args, run(s, *args)) == [[b"SET", b"k", b"v2", b"KEEPTTL"]]
    args = [b"SET", b"k", b"v3"]
    assert translate(s, args, run(s, *args)) == [[b"SET", b"k", b"v3"]]


def test_translate_skips_failures_and_reads():
    s = Store()
    run(s, "SET", "k", "1")
    cases = [
        [b"SET", b"k", b"2", b"NX"],  # condition not met
        [b"SET", b"k"],  # wrong arity
        [b"GET", b"k"],  # read
        [b"DEL", b"missing"],  # nothing deleted
        [b"LPOP", b"missing"],  # nothing popped
        [b"EXPIRE", b"missing", b"10"],  # no such key
    ]
    for args in cases:
        assert translate(s, args, run(s, *args)) == [], args


def test_translate_expire_variants():
    clock = FakeClock()
    s = Store(clock_ms=clock)
    run(s, "SET", "k", "v")
    args = [b"EXPIRE", b"k", b"100"]
    assert translate(s, args, run(s, *args)) == [
        [b"PEXPIREAT", b"k", str(clock() + 100_000).encode()]
    ]
    args = [b"EXPIRE", b"k", b"-1"]  # non-positive: key is deleted
    assert translate(s, args, run(s, *args)) == [[b"DEL", b"k"]]


def test_replay_rebuilds_state(tmp_path):
    clock = FakeClock()
    s = Store(clock_ms=clock)
    path = str(tmp_path / "a.aof")
    aof = AofWriter(path, "always")
    commands = [
        ("SET", "a", "1"), ("INCR", "a"), ("INCRBY", "a", "10"),
        ("SET", "s", "x", "EX", "100"),
        ("RPUSH", "l", "1", "2", "3"), ("LPOP", "l"), ("LPUSH", "l", "0"),
        ("HSET", "h", "f", "v", "g", "w"), ("HDEL", "h", "g"),
        ("SADD", "set", "a", "b", "c"), ("SREM", "set", "b"),
        ("ZADD", "z", "1", "a", "2", "b"), ("ZADD", "z", "5", "a"), ("ZREM", "z", "b"),
        ("SET", "gone", "x"), ("DEL", "gone"),
        ("EXPIRE", "l", "300"), ("PERSIST", "l"),
        ("SET", "t", "v", "PX", "5000"), ("SET", "t", "v2", "KEEPTTL"),
    ]
    for args in commands:
        logged(s, aof, *args)
    aof.close()
    t, count, cut = recover(path, clock)
    assert cut == 0
    assert state(t) == state(s)


def test_replay_keeps_absolute_deadlines(tmp_path):
    clock = FakeClock()
    s = Store(clock_ms=clock)
    path = str(tmp_path / "a.aof")
    aof = AofWriter(path, "always")
    logged(s, aof, "SET", "k", "v", "EX", "100")
    aof.close()
    later = FakeClock(clock() + 50_000)
    t, _, _ = recover(path, later)
    assert t.ttl_ms(b"k") == 50_000  # not restarted at 100s


def test_replay_does_not_expire_keys_midway(tmp_path):
    clock = FakeClock()
    s = Store(clock_ms=clock)
    path = str(tmp_path / "a.aof")
    aof = AofWriter(path, "always")
    logged(s, aof, "SET", "n", "1", "PX", "1000")
    logged(s, aof, "INCR", "n")
    aof.close()
    later = FakeClock(clock() + 60_000)  # replay long after the TTL passed
    t, _, _ = recover(path, later)
    # expired after loading, not resurrected as n=1 without a TTL
    assert t.ttl_ms(b"n") == -2
    assert t.exists(b"n") is False


def test_expiry_is_logged_as_del(tmp_path):
    clock = FakeClock()
    s = Store(clock_ms=clock)
    path = str(tmp_path / "a.aof")
    aof = AofWriter(path, "always")
    s.on_expire = lambda key: aof.append([b"DEL", key])
    logged(s, aof, "SET", "k", "v", "PX", "100")
    clock.advance(500)
    logged(s, aof, "LPUSH", "k", "x")  # lazily expires the old string, then makes a list
    aof.close()
    t, _, _ = recover(path, clock)
    assert state(t) == state(s)
    assert t.type_name(b"k") == "list"


def test_truncated_tail_is_dropped(tmp_path):
    path = tmp_path / "a.aof"
    good = encode_command([b"SET", b"a", b"1"]) + encode_command(
        [b"RPUSH", b"l", b"x", b"y"]
    )
    partial = encode_command([b"SET", b"b", b"2"])[:-5]
    path.write_bytes(good + partial)
    t, count, cut = recover(path)
    assert count == 2
    assert cut == len(partial)
    assert set(state(t)) == {b"a", b"l"}
    assert path.read_bytes() == good  # incomplete command removed from the file


def test_corrupt_aof_raises(tmp_path):
    path = tmp_path / "a.aof"
    path.write_bytes(
        encode_command([b"SET", b"a", b"1"])
        + b"GARBAGE\r\n"
        + encode_command([b"SET", b"b", b"2"])
    )
    with pytest.raises(AofError):
        replay(str(path), Store())


def test_rewrite_compacts_log_and_preserves_state(tmp_path):
    clock = FakeClock()
    s = Store(clock_ms=clock)
    path = str(tmp_path / "a.aof")
    aof = AofWriter(path, "always")
    for i in range(200):
        logged(s, aof, "SET", "counter", str(i))
    for i in range(50):
        logged(s, aof, "RPUSH", "l", str(i))
    for _ in range(40):
        logged(s, aof, "LPOP", "l")
    logged(s, aof, "HSET", "h", "a", "1")
    logged(s, aof, "ZADD", "z", "1", "a", "2", "b")
    logged(s, aof, "SADD", "set", "m")
    logged(s, aof, "SET", "ttl", "v", "EX", "100")
    aof.flush()
    before = aof.size
    aof.rewrite(s)
    assert aof.size < before
    logged(s, aof, "SET", "after", "rewrite")  # appending still works after a rewrite
    aof.close()
    assert not os.path.exists(path + ".tmp")
    t, _, _ = recover(path, clock)
    assert state(t) == state(s)


def test_always_policy_writes_on_flush(tmp_path):
    path = str(tmp_path / "a.aof")
    aof = AofWriter(path, "always")
    aof.append([b"PING"])
    assert os.path.getsize(path) == 0  # still only in the memory buffer
    aof.flush()
    assert os.path.getsize(path) == len(encode_command([b"PING"]))
    aof.close()


def test_everysec_marks_dirty_until_fsync(tmp_path):
    aof = AofWriter(str(tmp_path / "a.aof"), "everysec")
    aof.append([b"PING"])
    aof.flush()
    assert aof.dirty is True
    aof.fsync_now()
    assert aof.dirty is False
    aof.close()
    aof2 = AofWriter(str(tmp_path / "b.aof"), "always")
    aof2.append([b"PING"])
    aof2.flush()
    assert aof2.dirty is False  # already fsynced inside flush()
    aof2.close()

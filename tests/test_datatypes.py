import pytest

import miniredis.commands  # noqa: F401
from miniredis.commands.registry import dispatch
from miniredis.resp import RespParser
from miniredis.store import Store

NIL = b"$-1\r\n"
OK = b"+OK\r\n"
EMPTY = b"*0\r\n"
NONE_TYPE = b"+none\r\n"
WRONG = b"-WRONGTYPE Operation against a key holding the wrong kind of value\r\n"


def bulk(s: str) -> bytes:
    return b"$%d\r\n%s\r\n" % (len(s), s.encode())


def integer(n: int) -> bytes:
    return b":%d\r\n" % n


def array(*items: str) -> bytes:
    return b"*%d\r\n" % len(items) + b"".join(bulk(i) for i in items)


def run(store, *args):
    return dispatch(store, [a.encode() if isinstance(a, str) else a for a in args])


def items(reply: bytes) -> list[str]:
    """Decode an array-of-bulk-strings reply. It has the same wire shape as a
    command, so the RESP parser can read it."""
    p = RespParser()
    p.feed(reply)
    out = list(p.iter_commands())
    return [x.decode() for x in out[0]] if out else []


@pytest.fixture
def s():
    return Store()


# ---- lists --------------------------------------------------------------


def test_lpush_rpush_order(s):
    assert run(s, "LPUSH", "l", "a", "b", "c") == integer(3)  # list is: c b a
    assert run(s, "RPUSH", "l", "x", "y") == integer(5)
    assert items(run(s, "LRANGE", "l", "0", "-1")) == ["c", "b", "a", "x", "y"]


def test_lpop_rpop(s):
    run(s, "RPUSH", "l", "a", "b", "c")
    assert run(s, "LPOP", "l") == bulk("a")
    assert run(s, "RPOP", "l") == bulk("c")
    assert run(s, "LPOP", "l") == bulk("b")
    assert run(s, "LPOP", "l") == NIL
    assert run(s, "RPOP", "missing") == NIL


def test_pop_with_count(s):
    run(s, "RPUSH", "l", "a", "b", "c", "d")
    assert run(s, "LPOP", "l", "2") == array("a", "b")
    assert run(s, "RPOP", "l", "10") == array("d", "c")
    assert run(s, "TYPE", "l") == NONE_TYPE  # emptied list is deleted
    assert run(s, "LPOP", "l", "2") == b"*-1\r\n"
    assert run(s, "LPOP", "l", "-1").startswith(b"-ERR value is out of range")


def test_lrange_indexes(s):
    run(s, "RPUSH", "l", "a", "b", "c", "d", "e")
    assert items(run(s, "LRANGE", "l", "1", "3")) == ["b", "c", "d"]
    assert items(run(s, "LRANGE", "l", "-2", "-1")) == ["d", "e"]
    assert items(run(s, "LRANGE", "l", "0", "100")) == list("abcde")
    assert items(run(s, "LRANGE", "l", "-100", "1")) == ["a", "b"]
    assert run(s, "LRANGE", "l", "3", "1") == EMPTY
    assert run(s, "LRANGE", "l", "10", "20") == EMPTY
    assert run(s, "LRANGE", "nope", "0", "-1") == EMPTY
    assert run(s, "LRANGE", "l", "a", "1").startswith(b"-ERR value is not an integer")


def test_llen(s):
    assert run(s, "LLEN", "l") == integer(0)
    run(s, "RPUSH", "l", "a", "b", "c")
    assert run(s, "LLEN", "l") == integer(3)


def test_list_keeps_ttl(s):
    run(s, "RPUSH", "l", "a")
    run(s, "EXPIRE", "l", "100")
    run(s, "RPUSH", "l", "b")
    assert run(s, "TTL", "l") == integer(100)


# ---- hashes -------------------------------------------------------------


def test_hash_basics(s):
    assert run(s, "HSET", "h", "a", "1", "b", "2") == integer(2)
    assert run(s, "HSET", "h", "a", "9", "c", "3") == integer(1)  # a updated, c new
    assert run(s, "HGET", "h", "a") == bulk("9")
    assert run(s, "HGET", "h", "zzz") == NIL
    assert run(s, "HGET", "nope", "a") == NIL
    assert run(s, "HLEN", "h") == integer(3)
    assert run(s, "HEXISTS", "h", "b") == integer(1)
    assert run(s, "HEXISTS", "h", "zzz") == integer(0)


def test_hgetall(s):
    run(s, "HSET", "h", "a", "1", "b", "2")
    flat = items(run(s, "HGETALL", "h"))
    assert dict(zip(flat[::2], flat[1::2])) == {"a": "1", "b": "2"}
    assert run(s, "HGETALL", "nope") == EMPTY


def test_hdel_and_empty_hash_removed(s):
    run(s, "HSET", "h", "a", "1", "b", "2")
    assert run(s, "HDEL", "h", "a", "zzz") == integer(1)
    assert run(s, "HDEL", "h", "b") == integer(1)
    assert run(s, "EXISTS", "h") == integer(0)
    assert run(s, "HDEL", "h", "a") == integer(0)


def test_hset_odd_args(s):
    assert run(s, "HSET", "h", "a", "1", "b").startswith(b"-ERR wrong number of arguments")
    assert run(s, "EXISTS", "h") == integer(0)


# ---- sets ---------------------------------------------------------------


def test_set_basics(s):
    assert run(s, "SADD", "s", "a", "b", "a") == integer(2)
    assert run(s, "SADD", "s", "b", "c") == integer(1)
    assert sorted(items(run(s, "SMEMBERS", "s"))) == ["a", "b", "c"]
    assert run(s, "SCARD", "s") == integer(3)
    assert run(s, "SISMEMBER", "s", "a") == integer(1)
    assert run(s, "SISMEMBER", "s", "z") == integer(0)
    assert run(s, "SISMEMBER", "nope", "a") == integer(0)
    assert run(s, "SMEMBERS", "nope") == EMPTY


def test_srem_and_empty_set_removed(s):
    run(s, "SADD", "s", "a", "b")
    assert run(s, "SREM", "s", "a", "zzz") == integer(1)
    assert run(s, "SREM", "s", "b") == integer(1)
    assert run(s, "TYPE", "s") == NONE_TYPE


# ---- sorted sets --------------------------------------------------------


def test_zadd_and_zrange(s):
    assert run(s, "ZADD", "z", "3", "c", "1", "a", "2", "b") == integer(3)
    assert items(run(s, "ZRANGE", "z", "0", "-1")) == ["a", "b", "c"]
    assert items(run(s, "ZRANGE", "z", "1", "1")) == ["b"]


def test_zadd_update_moves_member(s):
    run(s, "ZADD", "z", "1", "a", "2", "b")
    assert run(s, "ZADD", "z", "5", "a", "2", "b") == integer(0)  # updates only
    assert items(run(s, "ZRANGE", "z", "0", "-1")) == ["b", "a"]
    assert run(s, "ZCARD", "z") == integer(2)


def test_zrange_withscores(s):
    run(s, "ZADD", "z", "1", "a", "2.5", "b", "-inf", "c", "inf", "d")
    assert items(run(s, "ZRANGE", "z", "0", "-1", "WITHSCORES")) == [
        "c", "-inf", "a", "1", "b", "2.5", "d", "inf",
    ]


def test_zrange_negative_and_out_of_range(s):
    run(s, "ZADD", "z", "1", "a", "2", "b", "3", "c")
    assert items(run(s, "ZRANGE", "z", "-2", "-1")) == ["b", "c"]
    assert items(run(s, "ZRANGE", "z", "0", "99")) == ["a", "b", "c"]
    assert run(s, "ZRANGE", "z", "5", "9") == EMPTY
    assert run(s, "ZRANGE", "z", "2", "0") == EMPTY
    assert run(s, "ZRANGE", "nope", "0", "-1") == EMPTY
    assert run(s, "ZRANGE", "z", "0", "-1", "BOGUS").startswith(b"-ERR syntax error")


def test_zrank(s):
    run(s, "ZADD", "z", "1", "a", "2", "b", "3", "c")
    assert run(s, "ZRANK", "z", "a") == integer(0)
    assert run(s, "ZRANK", "z", "c") == integer(2)
    assert run(s, "ZRANK", "z", "zzz") == NIL
    assert run(s, "ZRANK", "nope", "a") == NIL


def test_zrem_and_empty_zset_removed(s):
    run(s, "ZADD", "z", "1", "a", "2", "b")
    assert run(s, "ZREM", "z", "a", "zzz") == integer(1)
    assert items(run(s, "ZRANGE", "z", "0", "-1")) == ["b"]
    assert run(s, "ZRANK", "z", "b") == integer(0)
    assert run(s, "ZREM", "z", "b") == integer(1)
    assert run(s, "TYPE", "z") == NONE_TYPE


def test_zscore(s):
    run(s, "ZADD", "z", "1.5", "a")
    assert run(s, "ZSCORE", "z", "a") == bulk("1.5")
    assert run(s, "ZSCORE", "z", "zzz") == NIL


def test_zadd_invalid_input_applies_nothing(s):
    assert run(s, "ZADD", "z", "1", "a", "oops", "b").startswith(
        b"-ERR value is not a valid float"
    )
    assert run(s, "ZADD", "z", "nan", "a").startswith(b"-ERR value is not a valid float")
    assert run(s, "ZADD", "z", "1", "a", "2").startswith(b"-ERR syntax error")
    assert run(s, "EXISTS", "z") == integer(0)


# ---- INCR family, TYPE, KEYS, WRONGTYPE ---------------------------------


def test_incr_decr(s):
    assert run(s, "INCR", "n") == integer(1)
    assert run(s, "INCR", "n") == integer(2)
    assert run(s, "DECR", "n") == integer(1)
    assert run(s, "INCRBY", "n", "10") == integer(11)
    assert run(s, "DECRBY", "n", "20") == integer(-9)
    assert run(s, "GET", "n") == bulk("-9")
    run(s, "SET", "m", "41")
    assert run(s, "INCR", "m") == integer(42)


def test_incr_errors(s):
    run(s, "SET", "k", "abc")
    assert run(s, "INCR", "k").startswith(b"-ERR value is not an integer")
    assert run(s, "INCRBY", "n", "x").startswith(b"-ERR value is not an integer")
    run(s, "SET", "big", "9223372036854775807")
    assert run(s, "INCR", "big").startswith(b"-ERR increment or decrement would overflow")
    assert run(s, "GET", "big") == bulk("9223372036854775807")


def test_incr_keeps_ttl(s):
    run(s, "SET", "n", "5", "EX", "100")
    run(s, "INCR", "n")
    assert run(s, "TTL", "n") == integer(100)


def test_type(s):
    run(s, "SET", "str", "x")
    run(s, "RPUSH", "list", "x")
    run(s, "HSET", "hash", "f", "v")
    run(s, "SADD", "set", "m")
    run(s, "ZADD", "zset", "1", "m")
    assert run(s, "TYPE", "str") == b"+string\r\n"
    assert run(s, "TYPE", "list") == b"+list\r\n"
    assert run(s, "TYPE", "hash") == b"+hash\r\n"
    assert run(s, "TYPE", "set") == b"+set\r\n"
    assert run(s, "TYPE", "zset") == b"+zset\r\n"
    assert run(s, "TYPE", "nope") == NONE_TYPE


def test_keys_pattern(s):
    for k in ("user:1", "user:2", "order:1"):
        run(s, "SET", k, "x")
    assert sorted(items(run(s, "KEYS", "user:*"))) == ["user:1", "user:2"]
    assert sorted(items(run(s, "KEYS", "user:?"))) == ["user:1", "user:2"]
    assert sorted(items(run(s, "KEYS", "*"))) == ["order:1", "user:1", "user:2"]
    assert run(s, "KEYS", "zzz*") == EMPTY


def test_keys_skips_expired():
    t = [1_000_000]
    s2 = Store(clock_ms=lambda: t[0])
    run(s2, "SET", "a", "1", "PX", "100")
    run(s2, "SET", "b", "1")
    t[0] += 200
    assert items(run(s2, "KEYS", "*")) == ["b"]
    assert len(s2) == 1


def test_wrongtype_errors(s):
    run(s, "SET", "str", "x")
    run(s, "RPUSH", "list", "x")
    run(s, "HSET", "hash", "f", "v")
    run(s, "SADD", "set", "m")
    run(s, "ZADD", "zset", "1", "m")
    cases = [
        ("GET", "list"),
        ("INCR", "list"),
        ("LPUSH", "str", "x"),
        ("LRANGE", "hash", "0", "-1"),
        ("LPOP", "set"),
        ("HSET", "str", "f", "v"),
        ("HGET", "list", "f"),
        ("SADD", "hash", "m"),
        ("SMEMBERS", "zset"),
        ("ZADD", "set", "1", "m"),
        ("ZRANGE", "str", "0", "-1"),
        ("ZRANK", "list", "m"),
    ]
    for args in cases:
        assert run(s, *args) == WRONG, args


def test_set_overwrites_other_types(s):
    run(s, "RPUSH", "k", "a")
    assert run(s, "SET", "k", "v") == OK
    assert run(s, "TYPE", "k") == b"+string\r\n"
    assert run(s, "GET", "k") == bulk("v")

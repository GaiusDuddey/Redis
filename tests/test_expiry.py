import asyncio

import pytest

import miniredis.commands  # noqa: F401
from miniredis.commands.registry import dispatch
from miniredis.expiry import active_expire_cycle
from miniredis.server import Server
from miniredis.store import Store

OK = b"+OK\r\n"
NIL = b"$-1\r\n"


def bulk(s: str) -> bytes:
    return b"$%d\r\n%s\r\n" % (len(s), s.encode())


def integer(n: int) -> bytes:
    return b":%d\r\n" % n


class FakeClock:
    def __init__(self, start: int = 1_000_000) -> None:
        self.t = start

    def __call__(self) -> int:
        return self.t

    def advance(self, ms: int) -> None:
        self.t += ms


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(clock):
    return Store(clock_ms=clock)


def run(store, *args):
    return dispatch(store, [a.encode() if isinstance(a, str) else a for a in args])


def test_set_ex_expires(store, clock):
    assert run(store, "SET", "k", "v", "EX", "10") == OK
    assert run(store, "GET", "k") == bulk("v")
    clock.advance(9_999)
    assert run(store, "GET", "k") == bulk("v")
    clock.advance(2)
    assert run(store, "GET", "k") == NIL


def test_set_px_expires(store, clock):
    run(store, "SET", "k", "v", "PX", "500")
    clock.advance(501)
    assert run(store, "GET", "k") == NIL


def test_set_options_case_insensitive(store):
    assert run(store, "SET", "k", "v", "ex", "5") == OK
    assert run(store, "TTL", "k") == integer(5)


def test_plain_set_clears_ttl(store, clock):
    run(store, "SET", "k", "v", "EX", "10")
    run(store, "SET", "k", "v2")
    clock.advance(20_000)
    assert run(store, "GET", "k") == bulk("v2")
    assert run(store, "TTL", "k") == integer(-1)


def test_set_keepttl(store, clock):
    run(store, "SET", "k", "v", "EX", "10")
    run(store, "SET", "k", "v2", "KEEPTTL")
    assert run(store, "GET", "k") == bulk("v2")
    assert run(store, "TTL", "k") == integer(10)
    clock.advance(20_000)
    assert run(store, "GET", "k") == NIL


def test_set_nx_xx(store):
    assert run(store, "SET", "k", "1", "NX") == OK
    assert run(store, "SET", "k", "2", "NX") == NIL
    assert run(store, "GET", "k") == bulk("1")
    assert run(store, "SET", "missing", "x", "XX") == NIL
    assert run(store, "GET", "missing") == NIL
    assert run(store, "SET", "k", "3", "XX") == OK
    assert run(store, "GET", "k") == bulk("3")


def test_set_nx_succeeds_on_expired_key(store, clock):
    run(store, "SET", "k", "1", "PX", "100")
    clock.advance(200)
    assert run(store, "SET", "k", "2", "NX") == OK
    assert run(store, "GET", "k") == bulk("2")
    assert run(store, "TTL", "k") == integer(-1)


def test_set_syntax_errors(store):
    bad = [
        ("SET", "k", "v", "EX"),
        ("SET", "k", "v", "EX", "10", "PX", "10"),
        ("SET", "k", "v", "NX", "XX"),
        ("SET", "k", "v", "EX", "10", "KEEPTTL"),
        ("SET", "k", "v", "BOGUS"),
    ]
    for args in bad:
        assert run(store, *args).startswith(b"-ERR syntax error"), args


def test_set_invalid_expire(store):
    assert run(store, "SET", "k", "v", "EX", "0").startswith(
        b"-ERR invalid expire time in 'set'"
    )
    assert run(store, "SET", "k", "v", "PX", "-5").startswith(
        b"-ERR invalid expire time in 'set'"
    )
    assert run(store, "SET", "k", "v", "EX", "abc").startswith(
        b"-ERR value is not an integer"
    )
    assert run(store, "GET", "k") == NIL  # failed SETs must not set anything


def test_expire_and_ttl(store, clock):
    run(store, "SET", "k", "v")
    assert run(store, "TTL", "k") == integer(-1)
    assert run(store, "EXPIRE", "k", "100") == integer(1)
    assert run(store, "TTL", "k") == integer(100)
    assert run(store, "PTTL", "k") == integer(100_000)
    clock.advance(40_000)
    assert run(store, "TTL", "k") == integer(60)
    assert run(store, "PTTL", "k") == integer(60_000)


def test_ttl_rounding(store):
    run(store, "SET", "k", "v")
    run(store, "PEXPIRE", "k", "1499")
    assert run(store, "TTL", "k") == integer(1)
    run(store, "PEXPIRE", "k", "1500")
    assert run(store, "TTL", "k") == integer(2)


def test_ttl_and_expire_missing_key(store):
    assert run(store, "TTL", "nope") == integer(-2)
    assert run(store, "PTTL", "nope") == integer(-2)
    assert run(store, "EXPIRE", "nope", "10") == integer(0)
    assert run(store, "PEXPIRE", "nope", "10") == integer(0)
    assert run(store, "PERSIST", "nope") == integer(0)


def test_pexpire(store, clock):
    run(store, "SET", "k", "v")
    assert run(store, "PEXPIRE", "k", "250") == integer(1)
    clock.advance(251)
    assert run(store, "GET", "k") == NIL
    assert run(store, "TTL", "k") == integer(-2)


def test_expire_nonpositive_deletes_key(store):
    run(store, "SET", "k", "v")
    assert run(store, "EXPIRE", "k", "0") == integer(1)
    assert run(store, "EXISTS", "k") == integer(0)
    run(store, "SET", "k", "v")
    assert run(store, "EXPIRE", "k", "-10") == integer(1)
    assert run(store, "GET", "k") == NIL


def test_expire_invalid_args(store):
    run(store, "SET", "k", "v")
    assert run(store, "EXPIRE", "k", "abc").startswith(b"-ERR value is not an integer")
    assert run(store, "EXPIRE", "k", "99999999999999999").startswith(
        b"-ERR invalid expire time in 'expire'"
    )
    assert run(store, "PEXPIRE", "k", "9223372036854775807").startswith(
        b"-ERR invalid expire time in 'pexpire'"
    )
    assert run(store, "TTL", "k") == integer(-1)  # nothing was applied


def test_persist(store, clock):
    run(store, "SET", "k", "v", "EX", "10")
    assert run(store, "PERSIST", "k") == integer(1)
    assert run(store, "TTL", "k") == integer(-1)
    clock.advance(60_000)
    assert run(store, "GET", "k") == bulk("v")
    assert run(store, "PERSIST", "k") == integer(0)  # already has no TTL


def test_expire_replaces_existing_ttl(store, clock):
    run(store, "SET", "k", "v", "EX", "10")
    assert run(store, "EXPIRE", "k", "100") == integer(1)
    assert run(store, "TTL", "k") == integer(100)
    clock.advance(50_000)
    assert run(store, "GET", "k") == bulk("v")


def test_del_and_exists_ignore_expired_keys(store, clock):
    run(store, "SET", "a", "1", "PX", "10")
    run(store, "SET", "b", "2", "PX", "10")
    clock.advance(20)
    assert run(store, "EXISTS", "a") == integer(0)
    assert run(store, "DEL", "b") == integer(0)


def test_lazy_expiry_frees_memory(store, clock):
    run(store, "SET", "k", "v", "PX", "10")
    assert run(store, "DBSIZE") == integer(1)
    assert store.expires_count() == 1
    clock.advance(20)
    assert run(store, "DBSIZE") == integer(1)  # expired but nobody touched it yet
    assert run(store, "GET", "k") == NIL
    assert run(store, "DBSIZE") == integer(0)
    assert store.expires_count() == 0


def test_active_cycle_removes_unread_keys(store, clock):
    for i in range(1000):
        store.set(f"k{i}".encode(), b"v", expire_at_ms=clock.t + 100)
    store.set(b"keep", b"v")
    clock.advance(200)
    for _ in range(200):
        active_expire_cycle(store)
        if len(store) == 1:
            break
    assert len(store) == 1
    assert store.get(b"keep") == b"v"
    assert store.expires_count() == 0


def test_active_cycle_leaves_live_keys(store, clock):
    for i in range(100):
        store.set(f"k{i}".encode(), b"v", expire_at_ms=clock.t + 100_000)
    assert active_expire_cycle(store) == 0
    assert len(store) == 100


async def test_server_expires_keys_in_background():
    server = Server(port=0)
    await server.start()
    try:
        now = server.store.now_ms()
        for i in range(200):
            server.store.set(f"k{i}".encode(), b"v", expire_at_ms=now + 50)
        assert len(server.store) == 200
        await asyncio.sleep(0.6)  # nobody reads the keys: only the background task can remove them
        assert len(server.store) == 0
    finally:
        await server.stop()

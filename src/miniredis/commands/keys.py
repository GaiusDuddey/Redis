from miniredis.commands.registry import command
from miniredis.commands.util import ERR_NOT_INT, compute_deadline, parse_int
from miniredis.resp import encode_error, encode_integer
from miniredis.store import Store


@command("DEL", -2)
def del_(store: Store, args: list[bytes]) -> bytes:
    return encode_integer(sum(1 for key in args[1:] if store.delete(key)))


@command("EXISTS", -2)
def exists(store: Store, args: list[bytes]) -> bytes:
    # Real Redis counts duplicates: EXISTS a a -> 2 if a exists
    return encode_integer(sum(1 for key in args[1:] if store.exists(key)))


@command("DBSIZE", 1)
def dbsize(store: Store, args: list[bytes]) -> bytes:
    # Like real Redis, includes expired keys that haven't been removed yet.
    return encode_integer(len(store))


def _expire(store: Store, args: list[bytes], unit_ms: int, name: str) -> bytes:
    n = parse_int(args[2])
    if n is None:
        return ERR_NOT_INT
    now = store.now_ms()
    deadline = compute_deadline(now, n * unit_ms)
    if deadline is None:
        return encode_error(f"ERR invalid expire time in '{name}' command")
    key = args[1]
    if not store.exists(key):
        return encode_integer(0)
    if deadline <= now:  # non-positive TTL deletes the key right away
        store.delete(key)
        return encode_integer(1)
    store.set_expire(key, deadline)
    return encode_integer(1)


@command("EXPIRE", 3)
def expire(store: Store, args: list[bytes]) -> bytes:
    return _expire(store, args, 1000, "expire")


@command("PEXPIRE", 3)
def pexpire(store: Store, args: list[bytes]) -> bytes:
    return _expire(store, args, 1, "pexpire")


@command("TTL", 2)
def ttl(store: Store, args: list[bytes]) -> bytes:
    ms = store.ttl_ms(args[1])
    if ms < 0:
        return encode_integer(ms)
    return encode_integer((ms + 500) // 1000)  # rounds to nearest second, like Redis


@command("PTTL", 2)
def pttl(store: Store, args: list[bytes]) -> bytes:
    return encode_integer(store.ttl_ms(args[1]))


@command("PERSIST", 2)
def persist(store: Store, args: list[bytes]) -> bytes:
    return encode_integer(1 if store.persist(args[1]) else 0)

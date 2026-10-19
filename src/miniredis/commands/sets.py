from miniredis.commands.registry import command
from miniredis.commands.util import fetch
from miniredis.resp import encode_array, encode_bulk, encode_integer
from miniredis.store import Store


@command("SADD", -3)
def sadd(store: Store, args: list[bytes]) -> bytes:
    key = args[1]
    s, err = fetch(store, key, set)
    if err:
        return err
    if s is None:
        s = set()
        store.put(key, s)
    before = len(s)
    s.update(args[2:])
    return encode_integer(len(s) - before)


@command("SREM", -3)
def srem(store: Store, args: list[bytes]) -> bytes:
    key = args[1]
    s, err = fetch(store, key, set)
    if err:
        return err
    if s is None:
        return encode_integer(0)
    before = len(s)
    s.difference_update(args[2:])
    removed = before - len(s)
    if not s:
        store.delete(key)  # Redis never keeps an empty set around
    return encode_integer(removed)


@command("SMEMBERS", 2)
def smembers(store: Store, args: list[bytes]) -> bytes:
    s, err = fetch(store, args[1], set)
    if err:
        return err
    if s is None:
        return encode_array([])
    return encode_array([encode_bulk(m) for m in s])


@command("SISMEMBER", 3)
def sismember(store: Store, args: list[bytes]) -> bytes:
    s, err = fetch(store, args[1], set)
    if err:
        return err
    return encode_integer(1 if s is not None and args[2] in s else 0)


@command("SCARD", 2)
def scard(store: Store, args: list[bytes]) -> bytes:
    s, err = fetch(store, args[1], set)
    if err:
        return err
    return encode_integer(0 if s is None else len(s))

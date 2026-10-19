from miniredis.commands.registry import command, wrong_args
from miniredis.commands.util import fetch
from miniredis.resp import NULL_BULK, encode_array, encode_bulk, encode_integer
from miniredis.store import Store


@command("HSET", -4)
def hset(store: Store, args: list[bytes]) -> bytes:
    if (len(args) - 2) % 2 != 0:
        return wrong_args(args[0])
    key = args[1]
    h, err = fetch(store, key, dict)
    if err:
        return err
    if h is None:
        h = {}
        store.put(key, h)
    added = 0
    for i in range(2, len(args), 2):
        if args[i] not in h:
            added += 1
        h[args[i]] = args[i + 1]
    return encode_integer(added)


@command("HGET", 3)
def hget(store: Store, args: list[bytes]) -> bytes:
    h, err = fetch(store, args[1], dict)
    if err:
        return err
    if h is None or args[2] not in h:
        return NULL_BULK
    return encode_bulk(h[args[2]])


@command("HDEL", -3)
def hdel(store: Store, args: list[bytes]) -> bytes:
    key = args[1]
    h, err = fetch(store, key, dict)
    if err:
        return err
    if h is None:
        return encode_integer(0)
    removed = sum(1 for field in args[2:] if h.pop(field, None) is not None)
    if not h:
        store.delete(key)  # Redis never keeps an empty hash around
    return encode_integer(removed)


@command("HGETALL", 2)
def hgetall(store: Store, args: list[bytes]) -> bytes:
    h, err = fetch(store, args[1], dict)
    if err:
        return err
    if h is None:
        return encode_array([])
    out = []
    for field, value in h.items():
        out.append(encode_bulk(field))
        out.append(encode_bulk(value))
    return encode_array(out)


@command("HLEN", 2)
def hlen(store: Store, args: list[bytes]) -> bytes:
    h, err = fetch(store, args[1], dict)
    if err:
        return err
    return encode_integer(0 if h is None else len(h))


@command("HEXISTS", 3)
def hexists(store: Store, args: list[bytes]) -> bytes:
    h, err = fetch(store, args[1], dict)
    if err:
        return err
    return encode_integer(1 if h is not None and args[2] in h else 0)

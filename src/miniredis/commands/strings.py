from miniredis.commands.registry import command, wrong_args
from miniredis.commands.util import (
    ERR_NOT_INT,
    ERR_SYNTAX,
    INT64_MAX,
    INT64_MIN,
    compute_deadline,
    fetch,
    parse_int,
)
from miniredis.resp import NULL_BULK, OK, PONG, encode_bulk, encode_error, encode_integer
from miniredis.store import Store

ERR_BAD_EXPIRE = encode_error("ERR invalid expire time in 'set' command")
ERR_OVERFLOW = encode_error("ERR increment or decrement would overflow")


@command("PING", -1)
def ping(store: Store, args: list[bytes]) -> bytes:
    if len(args) == 1:
        return PONG
    if len(args) == 2:
        return encode_bulk(args[1])
    return wrong_args(args[0])


@command("ECHO", 2)
def echo(store: Store, args: list[bytes]) -> bytes:
    return encode_bulk(args[1])


@command("CLIENT", -2)
def client(store: Store, args: list[bytes]) -> bytes:
    # Stub: accepts CLIENT SETINFO / SETNAME sent by client libraries on connect.
    return OK


@command("SET", -3)
def set_(store: Store, args: list[bytes]) -> bytes:
    """SET key value [EX seconds | PX milliseconds | KEEPTTL] [NX | XX]"""
    key, value = args[1], args[2]
    expire_ms = None  # relative TTL in ms
    nx = xx = keep_ttl = False

    i = 3
    while i < len(args):
        opt = args[i].upper()
        if opt == b"NX":
            nx = True
        elif opt == b"XX":
            xx = True
        elif opt == b"KEEPTTL":
            keep_ttl = True
        elif opt in (b"EX", b"PX"):
            if expire_ms is not None or i + 1 >= len(args):
                return ERR_SYNTAX
            n = parse_int(args[i + 1])
            if n is None:
                return ERR_NOT_INT
            if n <= 0:
                return ERR_BAD_EXPIRE
            expire_ms = n * 1000 if opt == b"EX" else n
            i += 1
        else:
            return ERR_SYNTAX
        i += 1

    if (nx and xx) or (keep_ttl and expire_ms is not None):
        return ERR_SYNTAX

    deadline = None
    if expire_ms is not None:
        deadline = compute_deadline(store.now_ms(), expire_ms)
        if deadline is None:
            return ERR_BAD_EXPIRE

    if nx and store.exists(key):
        return NULL_BULK
    if xx and not store.exists(key):
        return NULL_BULK

    store.set(key, value, expire_at_ms=deadline, keep_ttl=keep_ttl)
    return OK


@command("GET", 2)
def get(store: Store, args: list[bytes]) -> bytes:
    value, err = fetch(store, args[1], bytes)
    if err:
        return err
    return NULL_BULK if value is None else encode_bulk(value)


def _incr(store: Store, key: bytes, delta: int) -> bytes:
    value, err = fetch(store, key, bytes)
    if err:
        return err
    if value is None:
        current = 0
    else:
        current = parse_int(value)
        if current is None:
            return ERR_NOT_INT
    new = current + delta
    if new > INT64_MAX or new < INT64_MIN:
        return ERR_OVERFLOW
    store.put(key, str(new).encode())  # put() keeps the key's TTL, like real Redis
    return encode_integer(new)


@command("INCR", 2)
def incr(store: Store, args: list[bytes]) -> bytes:
    return _incr(store, args[1], 1)


@command("DECR", 2)
def decr(store: Store, args: list[bytes]) -> bytes:
    return _incr(store, args[1], -1)


@command("INCRBY", 3)
def incrby(store: Store, args: list[bytes]) -> bytes:
    n = parse_int(args[2])
    if n is None:
        return ERR_NOT_INT
    return _incr(store, args[1], n)


@command("DECRBY", 3)
def decrby(store: Store, args: list[bytes]) -> bytes:
    n = parse_int(args[2])
    if n is None:
        return ERR_NOT_INT
    return _incr(store, args[1], -n)

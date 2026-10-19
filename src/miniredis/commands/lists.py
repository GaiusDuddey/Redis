from collections import deque
from itertools import islice

from miniredis.commands.registry import command, wrong_args
from miniredis.commands.util import ERR_NOT_INT, fetch, normalize_range, parse_int
from miniredis.resp import (
    NULL_BULK,
    encode_array,
    encode_bulk,
    encode_error,
    encode_integer,
)
from miniredis.store import Store

NULL_ARRAY = b"*-1\r\n"
ERR_POSITIVE = encode_error("ERR value is out of range, must be positive")


def _push(store: Store, args: list[bytes], left: bool) -> bytes:
    key = args[1]
    lst, err = fetch(store, key, deque)
    if err:
        return err
    if lst is None:
        lst = deque()
        store.put(key, lst)
    for element in args[2:]:
        if left:
            lst.appendleft(element)
        else:
            lst.append(element)
    return encode_integer(len(lst))


@command("LPUSH", -3)
def lpush(store: Store, args: list[bytes]) -> bytes:
    return _push(store, args, left=True)


@command("RPUSH", -3)
def rpush(store: Store, args: list[bytes]) -> bytes:
    return _push(store, args, left=False)


def _pop(store: Store, args: list[bytes], left: bool) -> bytes:
    if len(args) > 3:
        return wrong_args(args[0])
    key = args[1]
    lst, err = fetch(store, key, deque)
    if err:
        return err

    if len(args) == 3:  # POP key count
        count = parse_int(args[2])
        if count is None or count < 0:
            return ERR_POSITIVE
        if lst is None:
            return NULL_ARRAY
        out = []
        for _ in range(min(count, len(lst))):
            out.append(encode_bulk(lst.popleft() if left else lst.pop()))
        if not lst:
            store.delete(key)  # Redis never keeps an empty list around
        return encode_array(out)

    if lst is None:
        return NULL_BULK
    value = lst.popleft() if left else lst.pop()
    if not lst:
        store.delete(key)
    return encode_bulk(value)


@command("LPOP", -2)
def lpop(store: Store, args: list[bytes]) -> bytes:
    return _pop(store, args, left=True)


@command("RPOP", -2)
def rpop(store: Store, args: list[bytes]) -> bytes:
    return _pop(store, args, left=False)


@command("LRANGE", 4)
def lrange(store: Store, args: list[bytes]) -> bytes:
    start, stop = parse_int(args[2]), parse_int(args[3])
    if start is None or stop is None:
        return ERR_NOT_INT
    lst, err = fetch(store, args[1], deque)
    if err:
        return err
    if lst is None:
        return encode_array([])
    bounds = normalize_range(start, stop, len(lst))
    if bounds is None:
        return encode_array([])
    first, last = bounds
    return encode_array([encode_bulk(x) for x in islice(lst, first, last + 1)])


@command("LLEN", 2)
def llen(store: Store, args: list[bytes]) -> bytes:
    lst, err = fetch(store, args[1], deque)
    if err:
        return err
    return encode_integer(0 if lst is None else len(lst))

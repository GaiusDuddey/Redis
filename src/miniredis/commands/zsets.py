from miniredis.commands.registry import command
from miniredis.commands.util import (
    ERR_NOT_FLOAT,
    ERR_NOT_INT,
    ERR_SYNTAX,
    fetch,
    format_score,
    normalize_range,
    parse_float,
    parse_int,
)
from miniredis.datastructures.zset import ZSet
from miniredis.resp import NULL_BULK, encode_array, encode_bulk, encode_integer
from miniredis.store import Store


@command("ZADD", -4)
def zadd(store: Store, args: list[bytes]) -> bytes:
    """ZADD key score member [score member ...]"""
    if (len(args) - 2) % 2 != 0:
        return ERR_SYNTAX
    pairs = []
    for i in range(2, len(args), 2):
        score = parse_float(args[i])
        if score is None:
            return ERR_NOT_FLOAT  # nothing has been applied yet
        pairs.append((score, args[i + 1]))

    key = args[1]
    z, err = fetch(store, key, ZSet)
    if err:
        return err
    if z is None:
        z = ZSet()
        store.put(key, z)
    added = sum(1 for score, member in pairs if z.add(member, score))
    return encode_integer(added)


@command("ZRANGE", -4)
def zrange(store: Store, args: list[bytes]) -> bytes:
    """ZRANGE key start stop [WITHSCORES]"""
    withscores = False
    if len(args) == 5:
        if args[4].upper() != b"WITHSCORES":
            return ERR_SYNTAX
        withscores = True
    elif len(args) != 4:
        return ERR_SYNTAX
    start, stop = parse_int(args[2]), parse_int(args[3])
    if start is None or stop is None:
        return ERR_NOT_INT
    z, err = fetch(store, args[1], ZSet)
    if err:
        return err
    if z is None:
        return encode_array([])
    bounds = normalize_range(start, stop, len(z))
    if bounds is None:
        return encode_array([])
    out = []
    for member, score in z.range_by_rank(*bounds):
        out.append(encode_bulk(member))
        if withscores:
            out.append(encode_bulk(format_score(score)))
    return encode_array(out)


@command("ZRANK", 3)
def zrank(store: Store, args: list[bytes]) -> bytes:
    z, err = fetch(store, args[1], ZSet)
    if err:
        return err
    rank = None if z is None else z.rank(args[2])
    return NULL_BULK if rank is None else encode_integer(rank)


@command("ZREM", -3)
def zrem(store: Store, args: list[bytes]) -> bytes:
    key = args[1]
    z, err = fetch(store, key, ZSet)
    if err:
        return err
    if z is None:
        return encode_integer(0)
    removed = sum(1 for member in args[2:] if z.remove(member))
    if len(z) == 0:
        store.delete(key)  # Redis never keeps an empty sorted set around
    return encode_integer(removed)


@command("ZSCORE", 3)
def zscore(store: Store, args: list[bytes]) -> bytes:
    z, err = fetch(store, args[1], ZSet)
    if err:
        return err
    score = None if z is None else z.score(args[2])
    return NULL_BULK if score is None else encode_bulk(format_score(score))


@command("ZCARD", 2)
def zcard(store: Store, args: list[bytes]) -> bytes:
    z, err = fetch(store, args[1], ZSet)
    if err:
        return err
    return encode_integer(0 if z is None else len(z))

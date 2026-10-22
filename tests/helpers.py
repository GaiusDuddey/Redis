from collections import deque

import miniredis.commands  # noqa: F401
from miniredis.commands.registry import dispatch
from miniredis.datastructures.zset import ZSet


class FakeClock:
    def __init__(self, start: int = 1_000_000) -> None:
        self.t = start

    def __call__(self) -> int:
        return self.t

    def advance(self, ms: int) -> None:
        self.t += ms


def run(store, *args):
    return dispatch(store, [a.encode() if isinstance(a, str) else a for a in args])


def canon(value):
    if isinstance(value, bytes):
        return value
    if isinstance(value, deque):
        return list(value)
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, set):
        return frozenset(value)
    if isinstance(value, ZSet):
        return value.range_by_rank(0, len(value) - 1)
    raise TypeError(type(value))


def state(store):
    """Comparable picture of everything live in a store: {key: (value, deadline)}."""
    return {k: (canon(v), d) for k, v, d in store.iter_live()}

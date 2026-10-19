"""Keyspace with TTL metadata. Keys are bytes (binary-safe, like real Redis).

A value is one of:
  bytes  -> string      deque -> list      dict -> hash
  set    -> set         ZSet  -> sorted set

Expiry model: a key's deadline is an absolute unix time in milliseconds, kept in a
separate dict. Keys are expired lazily here (on every access) and actively by
expiry.py (background sampling), so keys that are never read again don't leak memory.
"""
import time
from collections import deque
from typing import Callable

from miniredis.datastructures.randomset import RandomSet
from miniredis.datastructures.zset import ZSet


def wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


class Store:
    def __init__(self, clock_ms: Callable[[], int] = wall_clock_ms) -> None:
        self._data: dict[bytes, object] = {}
        self._expires: dict[bytes, int] = {}  # key -> absolute deadline (ms)
        self._ttl_keys = RandomSet()  # same keys as _expires, for O(1) sampling
        self._clock_ms = clock_ms
        self.expired_keys = 0

    def __len__(self) -> int:
        """Number of keys in memory, including expired ones not yet removed."""
        return len(self._data)

    def now_ms(self) -> int:
        return self._clock_ms()

    def expires_count(self) -> int:
        return len(self._expires)

    # ---- expiration internals -------------------------------------------

    def expire_if_needed(self, key: bytes) -> bool:
        """Lazy expiration. Removes the key if its deadline passed.
        Returns True if the key was expired (and is now gone)."""
        deadline = self._expires.get(key)
        if deadline is None or self._clock_ms() <= deadline:
            return False
        self._remove(key)
        self.expired_keys += 1
        return True

    def _remove(self, key: bytes) -> None:
        self._data.pop(key, None)
        self._clear_ttl(key)

    def _set_ttl(self, key: bytes, deadline_ms: int) -> None:
        self._expires[key] = deadline_ms
        self._ttl_keys.add(key)

    def _clear_ttl(self, key: bytes) -> None:
        self._expires.pop(key, None)
        self._ttl_keys.discard(key)

    def sample_ttl_keys(self, n: int) -> list[bytes]:
        return self._ttl_keys.sample(n)

    # ---- generic value access -------------------------------------------

    def lookup(self, key: bytes):
        """The value stored at key (any type), or None. Applies lazy expiry."""
        if self.expire_if_needed(key):
            return None
        return self._data.get(key)

    def put(self, key: bytes, value) -> None:
        """Store a value but keep the key's existing TTL (used by INCR, LPUSH, ...)."""
        self._data[key] = value

    def type_name(self, key: bytes) -> str:
        value = self.lookup(key)
        if value is None:
            return "none"
        if isinstance(value, bytes):
            return "string"
        if isinstance(value, deque):
            return "list"
        if isinstance(value, dict):
            return "hash"
        if isinstance(value, set):
            return "set"
        if isinstance(value, ZSet):
            return "zset"
        return "none"

    def keys(self) -> list[bytes]:
        """All live keys. O(n): this is why real Redis tells you to use SCAN instead."""
        return [k for k in list(self._data) if not self.expire_if_needed(k)]

    # ---- string / keyspace operations -----------------------------------

    def get(self, key: bytes):
        if self.expire_if_needed(key):
            return None
        return self._data.get(key)

    def set(
        self,
        key: bytes,
        value,
        expire_at_ms: int | None = None,
        keep_ttl: bool = False,
    ) -> None:
        # An already-expired old value must not pass its TTL on to the new one.
        self.expire_if_needed(key)
        self._data[key] = value
        if keep_ttl:
            return
        if expire_at_ms is None:
            self._clear_ttl(key)  # plain SET removes any existing TTL
        else:
            self._set_ttl(key, expire_at_ms)

    def delete(self, key: bytes) -> bool:
        if self.expire_if_needed(key) or key not in self._data:
            return False
        self._remove(key)
        return True

    def exists(self, key: bytes) -> bool:
        if self.expire_if_needed(key):
            return False
        return key in self._data

    def set_expire(self, key: bytes, deadline_ms: int) -> bool:
        if not self.exists(key):
            return False
        self._set_ttl(key, deadline_ms)
        return True

    def ttl_ms(self, key: bytes) -> int:
        """-2 = no such key, -1 = key has no TTL, otherwise remaining ms."""
        if self.expire_if_needed(key) or key not in self._data:
            return -2
        deadline = self._expires.get(key)
        if deadline is None:
            return -1
        return max(0, deadline - self._clock_ms())

    def persist(self, key: bytes) -> bool:
        if not self.exists(key) or key not in self._expires:
            return False
        self._clear_ttl(key)
        return True

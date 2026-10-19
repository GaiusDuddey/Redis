"""Keyspace with TTL metadata. Keys and values are bytes (binary-safe, like real Redis).

Expiry model: a key's deadline is an absolute unix time in milliseconds, kept in a
separate dict. Keys are expired lazily here (on every access) and actively by
expiry.py (background sampling), so keys that are never read again don't leak memory.
"""
import time
from typing import Callable

from miniredis.datastructures.randomset import RandomSet


def wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


class Store:
    def __init__(self, clock_ms: Callable[[], int] = wall_clock_ms) -> None:
        self._data: dict[bytes, bytes] = {}
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

    # ---- keyspace operations --------------------------------------------

    def get(self, key: bytes) -> bytes | None:
        if self.expire_if_needed(key):
            return None
        return self._data.get(key)

    def set(
        self,
        key: bytes,
        value: bytes,
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

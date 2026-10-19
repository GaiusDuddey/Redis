"""Active expiration.

Lazy expiry (in Store) only removes a key when someone touches it. A key that is
never read again would stay in memory forever, so this background cycle samples
keys that have a TTL and deletes the expired ones. Same algorithm as real Redis:
  1. sample up to 20 keys with a TTL, delete the expired ones
  2. if more than 25% of the sample was expired, repeat immediately
  3. stop after a small time budget so clients are never blocked for long
"""
import asyncio
import logging
import time

from miniredis.store import Store

log = logging.getLogger("miniredis")

SAMPLE_SIZE = 20
REPEAT_THRESHOLD = 0.25
TIME_BUDGET_S = 0.025
INTERVAL_S = 0.1  # 10 cycles per second


def active_expire_cycle(
    store: Store,
    sample_size: int = SAMPLE_SIZE,
    time_budget_s: float = TIME_BUDGET_S,
) -> int:
    """One cycle. Returns how many keys were removed."""
    stop_at = time.monotonic() + time_budget_s
    removed = 0
    while True:
        sample = store.sample_ttl_keys(sample_size)
        if not sample:
            break
        expired = sum(1 for key in sample if store.expire_if_needed(key))
        removed += expired
        if expired / len(sample) <= REPEAT_THRESHOLD:
            break
        if time.monotonic() >= stop_at:
            break
    return removed


async def expiry_loop(store: Store, interval_s: float = INTERVAL_S) -> None:
    while True:
        await asyncio.sleep(interval_s)
        try:
            active_expire_cycle(store)
        except Exception:
            log.exception("active expiry cycle failed")

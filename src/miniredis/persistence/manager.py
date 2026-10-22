"""Ties the AOF and snapshots together: startup recovery, logging, background jobs."""
import asyncio
import logging
import os
import time

from miniredis.config import PersistenceConfig
from miniredis.persistence import snapshot
from miniredis.persistence.aof import AofWriter, replay, translate
from miniredis.store import Store

log = logging.getLogger("miniredis")


def _fsync_and_close(fd: int) -> None:
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Persistence:
    def __init__(self, store: Store, config: PersistenceConfig) -> None:
        self.store = store
        self.config = config
        self.aof: AofWriter | None = None
        self.aof_path = os.path.join(config.dir, "appendonly.aof")
        self.snapshot_path = os.path.join(config.dir, "dump.mrdb")
        self.last_snapshot = time.monotonic()
        self._closed = False
        store.persistence = self

    @property
    def aof_enabled(self) -> bool:
        return self.aof is not None

    # ---- startup recovery -------------------------------------------------

    def load(self) -> None:
        """Rebuild the dataset from disk. Same order as real Redis: if the AOF is
        enabled and exists it wins (it is the more complete record), otherwise use the
        snapshot. Raises PersistenceError if what's on disk is corrupt."""
        cfg = self.config
        if not cfg.enabled:
            return
        os.makedirs(cfg.dir, exist_ok=True)
        need_rewrite = False
        self.store.loading = True
        try:
            if cfg.appendonly and os.path.exists(self.aof_path):
                count, cut = replay(self.aof_path, self.store)
                log.info("AOF loaded: %d commands replayed", count)
            elif os.path.exists(self.snapshot_path):
                keys = snapshot.load(self.store, self.snapshot_path, self.store.now_ms())
                log.info("snapshot loaded: %d keys", keys)
                need_rewrite = cfg.appendonly  # a new AOF must start from this state
        finally:
            self.store.loading = False

        if cfg.appendonly:
            self.aof = AofWriter(self.aof_path, cfg.appendfsync)
            self.store.on_expire = self.log_expired
            if need_rewrite:
                self.rewrite_aof()

    # ---- logging (called by the server) -------------------------------------

    def log_command(self, args: list[bytes], reply: bytes) -> None:
        if self.aof is None:
            return
        for entry in translate(self.store, args, reply):
            self.aof.append(entry)

    def log_expired(self, key: bytes) -> None:
        if self.aof is not None:
            self.aof.append([b"DEL", key])

    def flush(self) -> None:
        if self.aof is not None:
            self.aof.flush()

    # ---- snapshots and rewrite ------------------------------------------------

    def save_snapshot(self) -> None:
        os.makedirs(self.config.dir, exist_ok=True)
        keys = snapshot.save(self.store, self.snapshot_path)
        self.last_snapshot = time.monotonic()
        log.info("snapshot saved: %d keys", keys)

    def rewrite_aof(self) -> None:
        if self.aof is None:
            return
        before = self.aof.size
        self.aof.rewrite(self.store)
        log.info("AOF rewritten: %d -> %d bytes", before, self.aof.size)

    # ---- background loop ------------------------------------------------------

    async def run(self) -> None:
        ticks = 0
        while True:
            await asyncio.sleep(0.1)
            try:
                self.flush()  # writes DELs logged by active expiry
                ticks += 1
                if ticks % 10 == 0:
                    await self._every_second()
            except Exception:
                log.exception("persistence task failed")

    async def _every_second(self) -> None:
        cfg = self.config
        aof = self.aof
        if aof is not None:
            if cfg.appendfsync == "everysec" and aof.dirty:
                # fsync a dup of the descriptor in a worker thread so the event loop
                # never waits on the disk. The dup stays valid even if the file is
                # replaced by a rewrite in the meantime.
                fd = os.dup(aof.fileno())
                aof.dirty = False
                await asyncio.get_running_loop().run_in_executor(None, _fsync_and_close, fd)
            if aof.size >= cfg.rewrite_min_size and aof.size >= 2 * max(aof.base_size, 1):
                self.rewrite_aof()  # log doubled since the last rewrite
        if (
            cfg.snapshot_interval > 0
            and time.monotonic() - self.last_snapshot >= cfg.snapshot_interval
        ):
            self.save_snapshot()

    # ---- shutdown -------------------------------------------------------------

    def close(self) -> None:
        """Flush and fsync everything. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        self.store.on_expire = None
        try:
            if self.aof is not None:
                self.aof.close()
            if self.config.snapshot_interval > 0:
                self.save_snapshot()
        except Exception:
            log.exception("error while closing persistence")

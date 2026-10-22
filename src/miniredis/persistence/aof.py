"""Append-only file: every write command is logged (in RESP) and replayed on startup.

Rules that make replay reproduce the exact same state:
  * Relative TTLs are logged as absolute deadlines: SET k v EX 10 becomes
    SET k v + PEXPIREAT k <unix ms>. Replaying "EX 10" a day later would hand the
    key a fresh 10 seconds.
  * When a key expires, a DEL is logged, so a later write to the same key name
    doesn't land on a resurrected old value.
  * Replay runs with expiry disabled (store.loading): the commands see the same
    state they saw the first time, and keys expire normally once loading is done.
"""
import logging
import os
from collections import deque

import miniredis.commands  # noqa: F401  (registers the handlers used during replay)
from miniredis.commands.registry import dispatch
from miniredis.commands.util import format_score
from miniredis.datastructures.zset import ZSet
from miniredis.persistence import PersistenceError, fsync_dir
from miniredis.resp import NULL_BULK, OK, ProtocolError, RespParser, encode_command
from miniredis.store import Store

log = logging.getLogger("miniredis")

WRITE_COMMANDS = {
    b"SET", b"DEL", b"EXPIRE", b"PEXPIRE", b"PEXPIREAT", b"PERSIST",
    b"INCR", b"DECR", b"INCRBY", b"DECRBY",
    b"LPUSH", b"RPUSH", b"LPOP", b"RPOP",
    b"HSET", b"HDEL", b"SADD", b"SREM", b"ZADD", b"ZREM",
}
CHUNK = 64  # elements per command when rewriting big collections


class AofError(PersistenceError):
    pass


def translate(store: Store, args: list[bytes], reply: bytes) -> list[list[bytes]]:
    """Which commands to append to the AOF for a command that just ran?
    Called after execution, so the store already holds the result."""
    name = args[0].upper()
    if name not in WRITE_COMMANDS or reply[:1] == b"-":
        return []  # reads and failed commands change nothing
    key = args[1]

    if name == b"SET":
        if reply != OK:
            return []  # NX/XX condition not met
        if b"KEEPTTL" in (a.upper() for a in args[3:]):
            return [[b"SET", key, args[2], b"KEEPTTL"]]
        out = [[b"SET", key, args[2]]]
        deadline = store.deadline_ms(key)
        if deadline is not None:  # SET ... EX/PX: log the absolute deadline
            out.append([b"PEXPIREAT", key, str(deadline).encode()])
        return out

    if name in (b"EXPIRE", b"PEXPIRE", b"PEXPIREAT"):
        if reply != b":1\r\n":
            return []
        deadline = store.deadline_ms(key)
        if deadline is None:  # non-positive TTL deleted the key
            return [[b"DEL", key]]
        return [[b"PEXPIREAT", key, str(deadline).encode()]]

    if reply == b":0\r\n" and name in (b"DEL", b"SREM", b"HDEL", b"ZREM", b"PERSIST"):
        return []  # nothing changed
    if reply in (NULL_BULK, b"*-1\r\n") and name in (b"LPOP", b"RPOP"):
        return []
    return [list(args)]


def rewrite_commands(store: Store):
    """The smallest command stream that rebuilds the current state."""
    for key, value, deadline in store.iter_live():
        if isinstance(value, bytes):
            yield [b"SET", key, value]
        elif isinstance(value, deque):
            items = list(value)
            for i in range(0, len(items), CHUNK):
                yield [b"RPUSH", key, *items[i : i + CHUNK]]
        elif isinstance(value, dict):
            flat = [x for field, v in value.items() for x in (field, v)]
            for i in range(0, len(flat), 2 * CHUNK):
                yield [b"HSET", key, *flat[i : i + 2 * CHUNK]]
        elif isinstance(value, set):
            items = list(value)
            for i in range(0, len(items), CHUNK):
                yield [b"SADD", key, *items[i : i + CHUNK]]
        elif isinstance(value, ZSet):
            pairs = value.range_by_rank(0, len(value) - 1)
            for i in range(0, len(pairs), CHUNK):
                flat = [x for m, s in pairs[i : i + CHUNK] for x in (format_score(s), m)]
                yield [b"ZADD", key, *flat]
        if deadline is not None:
            yield [b"PEXPIREAT", key, str(deadline).encode()]


class AofWriter:
    """Buffers commands in memory; flush() writes them to the file.

    fsync policy:
      always   fsync inside every flush (before the client gets its reply). Safest, slowest.
      everysec a background task fsyncs once per second. At most ~1s lost on power failure.
      no       never fsync explicitly; the OS decides (typically within ~30s).
    Every flush() hands the data to the OS, so a crash of this *process* loses nothing
    under any policy. The policies only matter when the whole machine loses power.
    """

    def __init__(self, path: str, fsync_policy: str = "everysec") -> None:
        if fsync_policy not in ("always", "everysec", "no"):
            raise ValueError(f"bad fsync policy {fsync_policy!r}")
        self.path = path
        self.policy = fsync_policy
        self._f = open(path, "ab")
        self._buf = bytearray()
        self.size = os.path.getsize(path)
        self.base_size = self.size  # size after the last rewrite/load (for auto-rewrite)
        self.dirty = False  # written to the OS but not fsynced yet
        self._closed = False

    def append(self, args: list[bytes]) -> None:
        self._buf += encode_command(args)

    def flush(self) -> None:
        if not self._buf:
            return
        data = bytes(self._buf)
        self._buf.clear()
        self._f.write(data)
        self._f.flush()
        self.size += len(data)
        if self.policy == "always":
            os.fsync(self._f.fileno())
        else:
            self.dirty = True

    def fsync_now(self) -> None:
        if self.dirty:
            os.fsync(self._f.fileno())
            self.dirty = False

    def fileno(self) -> int:
        return self._f.fileno()

    def rewrite(self, store: Store) -> None:
        """Compact the log: write the minimal commands for the current state to a temp
        file, fsync it, atomically rename it over the AOF, reopen for appending.

        Runs synchronously on the event loop, so no command can run meanwhile and no
        'rewrite buffer' is needed. Real Redis forks a child process to do this in the
        background and buffers new writes meanwhile."""
        self._buf.clear()  # pending entries are already reflected in the store
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "wb") as f:
                batch = bytearray()
                for args in rewrite_commands(store):
                    batch += encode_command(args)
                    if len(batch) >= 1 << 20:
                        f.write(batch)
                        batch.clear()
                f.write(batch)
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise
        self._f.close()
        try:
            os.replace(tmp, self.path)
        finally:
            self._f = open(self.path, "ab")  # the new file (or the old one if rename failed)
        fsync_dir(os.path.dirname(self.path) or ".")
        self.size = self.base_size = os.path.getsize(self.path)
        self.dirty = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.flush()
        try:
            os.fsync(self._f.fileno())
        finally:
            self._f.close()


def replay(path: str, store: Store) -> tuple[int, int]:
    """Re-execute every command in the AOF against store.
    Returns (commands_replayed, bytes_truncated).

    An incomplete command at the end (the process died mid-write) is cut off the file
    and loading continues. Anything else that isn't valid RESP raises AofError."""
    parser = RespParser(strict=True)
    size = os.path.getsize(path)
    fed = 0
    count = 0
    store.loading = True
    try:
        with open(path, "rb") as f:
            while chunk := f.read(1 << 20):
                parser.feed(chunk)
                fed += len(chunk)
                try:
                    for args in parser.iter_commands():
                        reply = dispatch(store, args)
                        if reply[:1] == b"-":
                            log.warning("AOF: %r failed during replay: %r", args[0], reply[:80])
                        count += 1
                except ProtocolError as e:
                    raise AofError(
                        f"{path}: corrupt AOF near byte {fed - parser.buffered}: {e}"
                    ) from e
    finally:
        store.loading = False
    cut = parser.buffered
    if cut:
        os.truncate(path, size - cut)
        log.warning("AOF: dropped %d bytes of an incomplete last command", cut)
    return count, cut

"""Point-in-time snapshot (like Redis's RDB): compact, one file, atomic.

Layout (big-endian):
  MAGIC
  records:  [0xFC u64 expire_ms]?  type(1 byte)  key  value
  0xFF
  u32 CRC32 of every byte before it

Writing is atomic: dump to <path>.tmp, fsync, rename over <path>, fsync the directory.
A crash at any point leaves either the old complete snapshot or the new complete one.
"""
import os
import struct
import zlib
from collections import deque

from miniredis.datastructures.zset import ZSet
from miniredis.persistence import PersistenceError, fsync_dir
from miniredis.store import Store

MAGIC = b"MINIREDIS0001"
OP_EXPIRE = 0xFC
OP_EOF = 0xFF
T_STRING, T_LIST, T_HASH, T_SET, T_ZSET = range(5)

_U32 = struct.Struct(">I")
_U64 = struct.Struct(">Q")
_F64 = struct.Struct(">d")


class SnapshotError(PersistenceError):
    pass


def _blob(b: bytes) -> bytes:
    return _U32.pack(len(b)) + b


class _CrcWriter:
    """Buffers writes, tracks a running CRC32 of everything written."""

    def __init__(self, f) -> None:
        self.f = f
        self.crc = 0
        self.buf = bytearray()

    def write(self, data: bytes) -> None:
        self.buf += data
        if len(self.buf) >= 1 << 20:
            self.flush()

    def flush(self) -> None:
        if self.buf:
            self.crc = zlib.crc32(self.buf, self.crc)
            self.f.write(self.buf)
            self.buf.clear()


def _encode_value(key: bytes, value) -> bytes:
    if isinstance(value, bytes):
        kind, body = T_STRING, _blob(value)
    elif isinstance(value, deque):
        kind = T_LIST
        body = _U32.pack(len(value)) + b"".join(_blob(x) for x in value)
    elif isinstance(value, dict):
        kind = T_HASH
        body = _U32.pack(len(value)) + b"".join(
            _blob(f) + _blob(v) for f, v in value.items()
        )
    elif isinstance(value, set):
        kind = T_SET
        body = _U32.pack(len(value)) + b"".join(_blob(m) for m in value)
    elif isinstance(value, ZSet):
        kind = T_ZSET
        pairs = value.range_by_rank(0, len(value) - 1)
        body = _U32.pack(len(pairs)) + b"".join(
            _blob(m) + _F64.pack(s) for m, s in pairs
        )
    else:
        raise SnapshotError(f"cannot serialize value of type {type(value).__name__}")
    return bytes([kind]) + _blob(key) + body


def save(store: Store, path: str) -> int:
    """Write a snapshot atomically. Returns the number of keys saved."""
    tmp = path + ".tmp"
    count = 0
    try:
        with open(tmp, "wb") as f:
            w = _CrcWriter(f)
            w.write(MAGIC)
            for key, value, deadline in store.iter_live():
                if deadline is not None:
                    w.write(bytes([OP_EXPIRE]) + _U64.pack(deadline))
                w.write(_encode_value(key, value))
                count += 1
            w.write(bytes([OP_EOF]))
            w.flush()
            f.write(_U32.pack(w.crc))
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise
    os.replace(tmp, path)
    fsync_dir(os.path.dirname(path) or ".")
    return count


def _read_blob(data: bytes, pos: int, end: int) -> tuple[bytes, int]:
    (n,) = _U32.unpack_from(data, pos)
    pos += 4
    if pos + n > end:
        raise SnapshotError("record runs past the end of the file")
    return data[pos : pos + n], pos + n


def _read_value(kind: int, data: bytes, pos: int, end: int):
    if kind == T_STRING:
        return _read_blob(data, pos, end)
    if kind in (T_LIST, T_HASH, T_SET, T_ZSET):
        (n,) = _U32.unpack_from(data, pos)
        pos += 4
        if kind == T_LIST:
            items = deque()
            for _ in range(n):
                item, pos = _read_blob(data, pos, end)
                items.append(item)
            return items, pos
        if kind == T_HASH:
            h = {}
            for _ in range(n):
                field, pos = _read_blob(data, pos, end)
                value, pos = _read_blob(data, pos, end)
                h[field] = value
            return h, pos
        if kind == T_SET:
            s = set()
            for _ in range(n):
                member, pos = _read_blob(data, pos, end)
                s.add(member)
            return s, pos
        z = ZSet()
        for _ in range(n):
            member, pos = _read_blob(data, pos, end)
            (score,) = _F64.unpack_from(data, pos)
            pos += 8
            z.add(member, score)
        return z, pos
    raise SnapshotError(f"unknown value type {kind}")


def load(store: Store, path: str, now_ms: int) -> int:
    """Load a snapshot into store. Keys already expired at now_ms are skipped.
    Returns the number of keys loaded. Raises SnapshotError if the file is bad."""
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < len(MAGIC) + 1 + 4 or not data.startswith(MAGIC):
        raise SnapshotError(f"{path}: not a miniredis snapshot")
    end = len(data) - 4
    if zlib.crc32(data[:end]) != _U32.unpack_from(data, end)[0]:
        raise SnapshotError(f"{path}: checksum mismatch (file is corrupt or truncated)")

    pos = len(MAGIC)
    count = 0
    try:
        while True:
            op = data[pos]
            pos += 1
            if op == OP_EOF:
                break
            deadline = None
            if op == OP_EXPIRE:
                (deadline,) = _U64.unpack_from(data, pos)
                pos += 8
                op = data[pos]
                pos += 1
            key, pos = _read_blob(data, pos, end)
            value, pos = _read_value(op, data, pos, end)
            if deadline is not None and deadline < now_ms:
                continue  # already expired
            store.restore(key, value, deadline)
            count += 1
    except (IndexError, struct.error) as e:
        raise SnapshotError(f"{path}: truncated or malformed record") from e
    if pos != end:
        raise SnapshotError(f"{path}: unexpected trailing data")
    return count

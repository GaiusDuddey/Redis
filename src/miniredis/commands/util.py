import re

from miniredis.resp import encode_error

INT64_MAX = 2**63 - 1
INT64_MIN = -(2**63)
_INT_RE = re.compile(rb"-?[0-9]+")

ERR_NOT_INT = encode_error("ERR value is not an integer or out of range")
ERR_SYNTAX = encode_error("ERR syntax error")


def parse_int(raw: bytes) -> int | None:
    """Strict signed 64-bit integer parse. None if invalid."""
    if not _INT_RE.fullmatch(raw):
        return None
    n = int(raw)
    if n > INT64_MAX or n < INT64_MIN:
        return None
    return n


def compute_deadline(now_ms: int, delta_ms: int) -> int | None:
    """now + delta, or None if the result doesn't fit in int64."""
    deadline = now_ms + delta_ms
    if deadline > INT64_MAX or deadline < INT64_MIN:
        return None
    return deadline


ERR_WRONGTYPE = encode_error(
    "WRONGTYPE Operation against a key holding the wrong kind of value"
)
ERR_NOT_FLOAT = encode_error("ERR value is not a valid float")


def fetch(store, key: bytes, kind):
    """Look up key and check its type.
    Returns (value, None) on success (value is None if the key is missing),
    or (None, error_reply) if the key holds a different type."""
    value = store.lookup(key)
    if value is None:
        return None, None
    if not isinstance(value, kind):
        return None, ERR_WRONGTYPE
    return value, None


def parse_float(raw: bytes) -> float | None:
    """Strict-ish float parse: accepts inf/-inf, rejects nan, spaces and underscores."""
    if b"_" in raw or raw != raw.strip():
        return None
    try:
        f = float(raw)
    except ValueError:
        return None
    if f != f:  # nan
        return None
    return f


def format_score(score: float) -> bytes:
    if score == float("inf"):
        return b"inf"
    if score == float("-inf"):
        return b"-inf"
    if score.is_integer() and abs(score) < 1e17:
        return str(int(score)).encode()
    return repr(score).encode()


def normalize_range(start: int, stop: int, length: int) -> tuple[int, int] | None:
    """Redis LRANGE/ZRANGE index rules: negatives count from the end, out-of-range
    is clamped. Returns inclusive (start, stop), or None for an empty range."""
    if start < 0:
        start += length
    if stop < 0:
        stop += length
    if start < 0:
        start = 0
    if start > stop or start >= length:
        return None
    if stop >= length:
        stop = length - 1
    return start, stop

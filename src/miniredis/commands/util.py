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

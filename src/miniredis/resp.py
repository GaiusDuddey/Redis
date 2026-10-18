"""RESP (REdis Serialization Protocol) parser and encoders."""

MAX_BULK_LEN = 512 * 1024 * 1024
MAX_INLINE_LEN = 64 * 1024


class ProtocolError(Exception):
    pass


class RespParser:
    """Incremental parser. feed() raw bytes, then iterate iter_commands().

    A command that has not fully arrived stays in the buffer untouched
    until the rest of its bytes show up.
    """

    def __init__(self) -> None:
        self._buf = bytearray()

    def feed(self, data: bytes) -> None:
        self._buf.extend(data)

    def iter_commands(self):
        while True:
            args = self._parse_one()
            if args is None:  # incomplete, wait for more data
                return
            if args:  # skip empty lines / empty arrays
                yield args

    def _parse_one(self):
        buf = self._buf
        if not buf:
            return None

        # Inline command (e.g. typed via telnet): "SET a b\r\n"
        if buf[0:1] != b"*":
            end = buf.find(b"\r\n")
            if end == -1:
                if len(buf) > MAX_INLINE_LEN:
                    raise ProtocolError("too big inline request")
                return None
            line = bytes(buf[:end])
            del buf[: end + 2]
            return line.split()

        # Array of bulk strings: *<n>\r\n($<len>\r\n<data>\r\n) * n
        end = buf.find(b"\r\n")
        if end == -1:
            return None
        try:
            count = int(buf[1:end])
        except ValueError:
            raise ProtocolError("invalid multibulk length")
        pos = end + 2
        if count <= 0:
            del buf[:pos]
            return []

        args = []
        for _ in range(count):
            if pos >= len(buf):
                return None
            if buf[pos : pos + 1] != b"$":
                raise ProtocolError(f"expected '$', got '{chr(buf[pos])}'")
            end = buf.find(b"\r\n", pos)
            if end == -1:
                return None
            try:
                length = int(buf[pos + 1 : end])
            except ValueError:
                raise ProtocolError("invalid bulk length")
            if length < 0 or length > MAX_BULK_LEN:
                raise ProtocolError("invalid bulk length")
            start = end + 2
            stop = start + length
            if len(buf) < stop + 2:
                return None
            if buf[stop : stop + 2] != b"\r\n":
                raise ProtocolError("bulk string not terminated by CRLF")
            args.append(bytes(buf[start:stop]))
            pos = stop + 2

        del buf[:pos]
        return args


OK = b"+OK\r\n"
PONG = b"+PONG\r\n"
NULL_BULK = b"$-1\r\n"


def encode_simple(s: str) -> bytes:
    return f"+{s}\r\n".encode()


def encode_error(msg: str) -> bytes:
    return f"-{msg}\r\n".encode()


def encode_integer(n: int) -> bytes:
    return f":{n}\r\n".encode()


def encode_bulk(value: bytes | None) -> bytes:
    if value is None:
        return NULL_BULK
    return b"$%d\r\n%s\r\n" % (len(value), value)


def encode_array(encoded_items: list[bytes]) -> bytes:
    """Items must already be encoded."""
    return b"*%d\r\n%s" % (len(encoded_items), b"".join(encoded_items))

import pytest

from miniredis.resp import (
    ProtocolError,
    RespParser,
    encode_bulk,
    encode_error,
    encode_integer,
)

SET_CMD = b"*3\r\n$3\r\nSET\r\n$3\r\nkey\r\n$5\r\nvalue\r\n"


def parse_all(data: bytes):
    p = RespParser()
    p.feed(data)
    return list(p.iter_commands())


def test_simple_command():
    assert parse_all(b"*1\r\n$4\r\nPING\r\n") == [[b"PING"]]


def test_set_command():
    assert parse_all(SET_CMD) == [[b"SET", b"key", b"value"]]


def test_two_pipelined_commands():
    data = b"*1\r\n$4\r\nPING\r\n" + SET_CMD
    assert parse_all(data) == [[b"PING"], [b"SET", b"key", b"value"]]


def test_split_at_every_possible_position():
    for i in range(1, len(SET_CMD)):
        p = RespParser()
        p.feed(SET_CMD[:i])
        assert list(p.iter_commands()) == [], f"split at {i}"
        p.feed(SET_CMD[i:])
        assert list(p.iter_commands()) == [[b"SET", b"key", b"value"]], f"split at {i}"


def test_byte_by_byte():
    p = RespParser()
    got = []
    for b in SET_CMD:
        p.feed(bytes([b]))
        got.extend(p.iter_commands())
    assert got == [[b"SET", b"key", b"value"]]


def test_binary_safe_value_with_crlf():
    assert parse_all(b"*2\r\n$3\r\nGET\r\n$4\r\na\r\nb\r\n") == [[b"GET", b"a\r\nb"]]


def test_empty_bulk_string():
    assert parse_all(b"*2\r\n$3\r\nGET\r\n$0\r\n\r\n") == [[b"GET", b""]]


def test_inline_commands():
    assert parse_all(b"PING\r\n") == [[b"PING"]]
    assert parse_all(b"SET a b\r\n") == [[b"SET", b"a", b"b"]]


def test_empty_inline_line_ignored():
    assert parse_all(b"\r\n") == []


def test_invalid_bulk_length():
    with pytest.raises(ProtocolError):
        parse_all(b"*1\r\n$abc\r\n")


def test_missing_dollar():
    with pytest.raises(ProtocolError):
        parse_all(b"*1\r\n+PING\r\n")


def test_encoders():
    assert encode_bulk(b"hi") == b"$2\r\nhi\r\n"
    assert encode_bulk(None) == b"$-1\r\n"
    assert encode_bulk(b"") == b"$0\r\n\r\n"
    assert encode_integer(42) == b":42\r\n"
    assert encode_error("ERR boom") == b"-ERR boom\r\n"

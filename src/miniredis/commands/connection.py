from miniredis.commands.registry import command
from miniredis.resp import encode_array, encode_bulk, encode_error, encode_integer
from miniredis.store import Store


@command("HELLO", -1)
def hello(store: Store, args: list[bytes]) -> bytes:
    """Handshake sent by client libraries on connect. We only speak RESP2."""
    if len(args) >= 2:
        try:
            version = int(args[1])
        except ValueError:
            return encode_error("ERR Protocol version is not an integer or out of range")
        if version != 2:
            return encode_error("NOPROTO sorry, this protocol version is not supported")
    return encode_array(
        [
            encode_bulk(b"server"), encode_bulk(b"redis"),
            encode_bulk(b"version"), encode_bulk(b"0.1.0"),
            encode_bulk(b"proto"), encode_integer(2),
            encode_bulk(b"id"), encode_integer(1),
            encode_bulk(b"mode"), encode_bulk(b"standalone"),
            encode_bulk(b"role"), encode_bulk(b"master"),
            encode_bulk(b"modules"), encode_array([]),
        ]
    )

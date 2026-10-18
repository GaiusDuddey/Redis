from miniredis.commands.registry import command, wrong_args
from miniredis.resp import NULL_BULK, OK, PONG, encode_bulk
from miniredis.store import Store


@command("PING", -1)
def ping(store: Store, args: list[bytes]) -> bytes:
    if len(args) == 1:
        return PONG
    if len(args) == 2:
        return encode_bulk(args[1])
    return wrong_args(args[0])


@command("ECHO", 2)
def echo(store: Store, args: list[bytes]) -> bytes:
    return encode_bulk(args[1])


@command("CLIENT", -2)
def client(store: Store, args: list[bytes]) -> bytes:
    # Stub: accepts CLIENT SETINFO / SETNAME sent by client libraries on connect.
    return OK


@command("SET", 3)
def set_(store: Store, args: list[bytes]) -> bytes:
    store.set(args[1], args[2])
    return OK


@command("GET", 2)
def get(store: Store, args: list[bytes]) -> bytes:
    value = store.get(args[1])
    return NULL_BULK if value is None else encode_bulk(value)

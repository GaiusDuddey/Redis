from miniredis.commands.registry import command
from miniredis.resp import encode_integer
from miniredis.store import Store


@command("DEL", -2)
def del_(store: Store, args: list[bytes]) -> bytes:
    return encode_integer(sum(1 for key in args[1:] if store.delete(key)))


@command("EXISTS", -2)
def exists(store: Store, args: list[bytes]) -> bytes:
    # Real Redis counts duplicates: EXISTS a a -> 2 if a exists
    return encode_integer(sum(1 for key in args[1:] if store.exists(key)))

from miniredis.commands.registry import command
from miniredis.resp import OK, encode_error, encode_simple
from miniredis.store import Store


@command("SAVE", 1)
def save(store: Store, args: list[bytes]) -> bytes:
    """Write a snapshot now (blocks the server while it runs)."""
    if store.persistence is None:
        return encode_error("ERR persistence is not available")
    store.persistence.save_snapshot()
    return OK


@command("BGREWRITEAOF", 1)
def bgrewriteaof(store: Store, args: list[bytes]) -> bytes:
    """Compact the AOF. Real Redis does this in a forked child; ours runs
    synchronously on the event loop."""
    p = store.persistence
    if p is None or not p.aof_enabled:
        return encode_error("ERR AOF is not enabled (start the server with --appendonly)")
    p.rewrite_aof()
    return encode_simple("Background append only file rewriting started")

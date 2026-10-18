"""Command name -> handler table and dispatcher."""
import logging
from typing import Callable

from miniredis.resp import encode_error
from miniredis.store import Store

log = logging.getLogger("miniredis")

Handler = Callable[[Store, list[bytes]], bytes]
_COMMANDS: dict[bytes, tuple[Handler, int]] = {}


def command(name: str, arity: int):
    """arity > 0: exactly that many args (incl. command name).
    arity < 0: at least abs(arity) args."""

    def decorator(fn: Handler) -> Handler:
        _COMMANDS[name.upper().encode()] = (fn, arity)
        return fn

    return decorator


def wrong_args(name: bytes) -> bytes:
    return encode_error(
        f"ERR wrong number of arguments for '{name.decode(errors='replace').lower()}' command"
    )


def dispatch(store: Store, args: list[bytes]) -> bytes:
    name = args[0].upper()
    entry = _COMMANDS.get(name)
    if entry is None:
        shown = args[0].decode(errors="replace")
        return encode_error(f"ERR unknown command '{shown}'")
    handler, arity = entry
    if (arity > 0 and len(args) != arity) or (arity < 0 and len(args) < -arity):
        return wrong_args(name)
    try:
        return handler(store, args)
    except Exception:
        log.exception("handler crashed for %r", name)
        return encode_error("ERR internal error")

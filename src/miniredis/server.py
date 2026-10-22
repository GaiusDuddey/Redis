"""asyncio TCP server. One thread, one event loop: commands never run in parallel,
so every command is atomic and no locks are needed. Active expiry and the persistence
jobs run on the same loop, so they can never interleave with a command either."""
import asyncio
import logging

import miniredis.commands  # noqa: F401  (registers command handlers)
from miniredis.commands.registry import dispatch
from miniredis.config import PersistenceConfig
from miniredis.expiry import expiry_loop
from miniredis.persistence.manager import Persistence
from miniredis.resp import ProtocolError, RespParser, encode_error
from miniredis.store import Store

log = logging.getLogger("miniredis")


class Server:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 6379,
        persistence_config: PersistenceConfig | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.store = Store()
        self.persistence = Persistence(self.store, persistence_config or PersistenceConfig())
        self._server: asyncio.Server | None = None
        self._tasks: list[asyncio.Task] = []
        self._writers: set[asyncio.StreamWriter] = set()

    async def handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        log.info("client connected: %s", peer)
        self._writers.add(writer)
        parser = RespParser()
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                parser.feed(data)

                out = bytearray()
                close = False
                try:
                    for args in parser.iter_commands():
                        reply = dispatch(self.store, args)
                        self.persistence.log_command(args, reply)
                        out += reply
                except ProtocolError as e:
                    out += encode_error(f"ERR Protocol error: {e}")
                    close = True

                # Persist BEFORE replying: with appendfsync=always the client only sees
                # a reply once the write is on disk.
                self.persistence.flush()

                if out:
                    writer.write(out)
                    await writer.drain()
                if close:
                    break
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            self._writers.discard(writer)
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
            log.info("client disconnected: %s", peer)

    async def start(self) -> None:
        self.persistence.load()  # recover from disk before accepting any client
        self._server = await asyncio.start_server(
            self.handle_client, self.host, self.port
        )
        self.port = self._server.sockets[0].getsockname()[1]
        self._tasks = [
            asyncio.create_task(expiry_loop(self.store)),
            asyncio.create_task(self.persistence.run()),
        ]

    async def serve_forever(self) -> None:
        await self.start()
        log.info("miniredis listening on %s:%d", self.host, self.port)
        try:
            await self._server.serve_forever()
        finally:
            await self.stop()  # Ctrl+C lands here: flush and snapshot before exiting

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        # Synchronous, so no background task can run between cancel and close.
        self.persistence.close()
        for t in self._tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks = []
        if self._server is None:
            return
        self._server.close()
        for w in list(self._writers):
            w.close()
        await self._server.wait_closed()

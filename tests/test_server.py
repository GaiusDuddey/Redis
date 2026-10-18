"""Integration tests: real redis-py client against our server over TCP.

The server runs in a background thread with its own event loop, because the
sync redis-py client would otherwise block the loop the server runs on."""
import asyncio
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis

from miniredis.server import Server


class ServerThread(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.ready = threading.Event()
        self.port = None
        self.loop = None
        self._stop_event = None

    def run(self):
        asyncio.run(self._main())

    async def _main(self):
        self.loop = asyncio.get_running_loop()
        self._stop_event = asyncio.Event()
        server = Server(port=0)  # port 0 = OS picks a free port
        await server.start()
        self.port = server.port
        self.ready.set()
        await self._stop_event.wait()
        await server.stop()

    def stop(self):
        self.loop.call_soon_threadsafe(self._stop_event.set)
        self.join(timeout=5)


@pytest.fixture
def server_port():
    t = ServerThread()
    t.start()
    assert t.ready.wait(5), "server did not start"
    yield t.port
    t.stop()


@pytest.fixture
def client(server_port):
    c = redis.Redis(protocol=2, host="127.0.0.1", port=server_port, decode_responses=True)
    yield c
    c.close()


def test_ping(client):
    assert client.ping() is True


def test_echo(client):
    assert client.echo("hello") == "hello"


def test_set_get(client):
    assert client.set("a", "1") is True
    assert client.get("a") == "1"


def test_get_missing(client):
    assert client.get("nope") is None


def test_del_exists(client):
    client.set("a", "1")
    client.set("b", "2")
    assert client.exists("a", "b", "c") == 2
    assert client.delete("a", "c") == 1
    assert client.exists("a") == 0


def test_value_with_spaces_and_crlf(client):
    value = "hello world\r\nsecond line"
    client.set("k", value)
    assert client.get("k") == value


def test_unknown_command_error(client):
    with pytest.raises(redis.ResponseError):
        client.execute_command("FOO")


def test_wrong_arity_error(client):
    with pytest.raises(redis.ResponseError):
        client.execute_command("GET")


def test_large_value_spans_many_packets(client):
    value = "x" * (2 * 1024 * 1024)
    client.set("big", value)
    assert client.get("big") == value


def test_pipeline(client):
    pipe = client.pipeline(transaction=False)
    pipe.set("a", "1")
    pipe.set("b", "2")
    pipe.get("a")
    pipe.get("b")
    assert pipe.execute() == [True, True, "1", "2"]


def test_two_clients_share_data(server_port):
    c1 = redis.Redis(protocol=2, port=server_port, decode_responses=True)
    c2 = redis.Redis(protocol=2, port=server_port, decode_responses=True)
    c1.set("shared", "yes")
    assert c2.get("shared") == "yes"
    c1.close()
    c2.close()


def test_many_concurrent_clients(server_port):
    def worker(n):
        c = redis.Redis(protocol=2, port=server_port, decode_responses=True)
        for i in range(100):
            c.set(f"w{n}:{i}", str(i))
            assert c.get(f"w{n}:{i}") == str(i)
        c.close()
        return True

    with ThreadPoolExecutor(max_workers=20) as ex:
        assert all(ex.map(worker, range(20)))


def test_command_split_across_tcp_packets(server_port):
    chunks = [b"*3\r\n$3\r\nSE", b"T\r\n$1\r\nk\r\n$", b"1\r\nv\r", b"\n"]
    with socket.create_connection(("127.0.0.1", server_port), timeout=3) as s:
        for chunk in chunks:
            s.sendall(chunk)
            time.sleep(0.05)
        assert s.recv(100) == b"+OK\r\n"
        s.sendall(b"*2\r\n$3\r\nGET\r\n$1\r\nk\r\n")
        assert s.recv(100) == b"$1\r\nv\r\n"

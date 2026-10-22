"""Crash-recovery tests: real server processes, killed with SIGKILL."""
import signal
import socket
import subprocess
import sys
import time

import pytest
import redis


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start(port, data_dir, *flags):
    proc = subprocess.Popen(
        [sys.executable, "-m", "miniredis", "--port", str(port), "--dir", str(data_dir), *flags],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 10
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"server exited early with code {proc.returncode}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc
        except OSError:
            time.sleep(0.05)
    proc.kill()
    raise RuntimeError("server did not start")


@pytest.fixture
def procs():
    started = []
    yield started
    for p in started:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=5)


def launch(procs, data_dir, *flags):
    port = free_port()
    proc = start(port, data_dir, *flags)
    procs.append(proc)
    return proc, port


def connect(port):
    return redis.Redis(port=port, protocol=2, decode_responses=True)


def crash(proc):
    proc.kill()  # SIGKILL: no shutdown code gets to run
    proc.wait(timeout=5)


def write_data(c):
    c.set("str", "hello")
    c.set("ttl", "v", ex=1000)
    c.incr("n")
    c.incr("n", 41)
    c.rpush("list", "a", "b", "c")
    c.lpop("list")
    c.hset("hash", mapping={"f": "1", "g": "2"})
    c.hdel("hash", "g")
    c.sadd("set", "x", "y")
    c.zadd("z", {"a": 1, "b": 2})
    c.zrem("z", "b")
    c.set("gone", "x")
    c.delete("gone")


def check_data(c):
    assert c.get("str") == "hello"
    assert c.get("n") == "42"
    assert 900 < c.ttl("ttl") <= 1000
    assert c.lrange("list", 0, -1) == ["b", "c"]
    assert c.hgetall("hash") == {"f": "1"}
    assert c.smembers("set") == {"x", "y"}
    assert c.zrange("z", 0, -1, withscores=True) == [("a", 1.0)]
    assert c.exists("gone") == 0


@pytest.mark.parametrize("policy", ["always", "everysec", "no"])
def test_aof_survives_kill(tmp_path, procs, policy):
    # Every batch is handed to the OS before the reply, so killing the *process*
    # loses nothing under any policy. fsync only matters for power loss.
    flags = ["--appendonly", "--appendfsync", policy]
    proc, port = launch(procs, tmp_path, *flags)
    c = connect(port)
    write_data(c)
    c.close()
    crash(proc)

    _, port2 = launch(procs, tmp_path, *flags)
    check_data(connect(port2))


def test_snapshot_survives_kill(tmp_path, procs):
    flags = ["--snapshot-interval", "3600"]
    proc, port = launch(procs, tmp_path, *flags)
    c = connect(port)
    write_data(c)
    assert c.save() is True
    c.close()
    crash(proc)

    _, port2 = launch(procs, tmp_path, *flags)
    check_data(connect(port2))


def test_graceful_shutdown_writes_final_snapshot(tmp_path, procs):
    flags = ["--snapshot-interval", "3600"]
    proc, port = launch(procs, tmp_path, *flags)
    c = connect(port)
    c.set("k", "v")
    c.close()
    proc.send_signal(signal.SIGINT)  # same as Ctrl+C
    proc.wait(timeout=10)
    assert (tmp_path / "dump.mrdb").exists()

    _, port2 = launch(procs, tmp_path, *flags)
    assert connect(port2).get("k") == "v"


def test_corrupt_aof_refuses_to_start(tmp_path):
    (tmp_path / "appendonly.aof").write_bytes(
        b"*1\r\n$4\r\nPING\r\nNOT RESP AT ALL\r\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "miniredis", "--port", str(free_port()),
         "--dir", str(tmp_path), "--appendonly"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    assert proc.wait(timeout=10) == 1


def test_rewrite_then_crash(tmp_path, procs):
    flags = ["--appendonly", "--appendfsync", "always"]
    proc, port = launch(procs, tmp_path, *flags)
    c = connect(port)
    for i in range(300):
        c.set("k", str(i))
    aof = tmp_path / "appendonly.aof"
    big = aof.stat().st_size
    assert c.execute_command("BGREWRITEAOF")
    assert aof.stat().st_size < big / 10
    c.set("after", "rewrite")
    c.close()
    crash(proc)

    _, port2 = launch(procs, tmp_path, *flags)
    c = connect(port2)
    assert c.get("k") == "299"
    assert c.get("after") == "rewrite"

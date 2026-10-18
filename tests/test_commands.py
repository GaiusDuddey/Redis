import miniredis.commands  # noqa: F401
from miniredis.commands.registry import dispatch
from miniredis.store import Store


def run(store, *args):
    return dispatch(store, [a.encode() if isinstance(a, str) else a for a in args])


def test_ping():
    s = Store()
    assert run(s, "PING") == b"+PONG\r\n"
    assert run(s, "PING", "hi") == b"$2\r\nhi\r\n"


def test_echo():
    assert run(Store(), "ECHO", "hello") == b"$5\r\nhello\r\n"


def test_set_get():
    s = Store()
    assert run(s, "SET", "k", "v") == b"+OK\r\n"
    assert run(s, "GET", "k") == b"$1\r\nv\r\n"


def test_get_missing_is_null():
    assert run(Store(), "GET", "nope") == b"$-1\r\n"


def test_overwrite():
    s = Store()
    run(s, "SET", "k", "1")
    run(s, "SET", "k", "2")
    assert run(s, "GET", "k") == b"$1\r\n2\r\n"


def test_command_names_case_insensitive():
    s = Store()
    assert run(s, "set", "k", "v") == b"+OK\r\n"
    assert run(s, "gEt", "k") == b"$1\r\nv\r\n"


def test_del_and_exists():
    s = Store()
    run(s, "SET", "a", "1")
    run(s, "SET", "b", "2")
    assert run(s, "EXISTS", "a", "b", "c") == b":2\r\n"
    assert run(s, "EXISTS", "a", "a") == b":2\r\n"
    assert run(s, "DEL", "a", "c") == b":1\r\n"
    assert run(s, "EXISTS", "a") == b":0\r\n"


def test_unknown_command():
    assert run(Store(), "FOO").startswith(b"-ERR unknown command 'FOO'")


def test_wrong_arity():
    assert run(Store(), "GET").startswith(b"-ERR wrong number of arguments")
    assert run(Store(), "SET", "a").startswith(b"-ERR wrong number of arguments")
    assert run(Store(), "DEL").startswith(b"-ERR wrong number of arguments")


def test_hello_resp2():
    r = run(Store(), "HELLO", "2")
    assert r.startswith(b"*14\r\n")
    assert b"proto" in r


def test_hello_without_version():
    assert run(Store(), "HELLO").startswith(b"*14\r\n")


def test_hello_resp3_rejected():
    assert run(Store(), "HELLO", "3").startswith(b"-NOPROTO")

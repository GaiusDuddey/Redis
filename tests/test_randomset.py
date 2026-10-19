from miniredis.datastructures.randomset import RandomSet


def test_add_discard_contains():
    s = RandomSet()
    s.add(b"a")
    s.add(b"b")
    s.add(b"a")  # duplicate ignored
    assert len(s) == 2
    assert b"a" in s
    s.discard(b"a")
    assert b"a" not in s
    assert len(s) == 1
    s.discard(b"zzz")  # unknown item: no error
    assert len(s) == 1


def test_discard_keeps_positions_consistent():
    s = RandomSet()
    for i in range(100):
        s.add(i)
    for i in range(0, 100, 2):
        s.discard(i)
    assert len(s) == 50
    assert sorted(s.sample(50)) == list(range(1, 100, 2))
    for i in range(1, 100, 2):
        s.discard(i)
    assert len(s) == 0
    assert s.sample(5) == []


def test_sample_size():
    s = RandomSet()
    for i in range(100):
        s.add(i)
    out = s.sample(20)
    assert len(out) == 20
    assert len(set(out)) == 20
    assert len(s.sample(500)) == 100

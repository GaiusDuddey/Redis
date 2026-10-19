import random

from miniredis.datastructures.skiplist import SkipList


def members(sl):
    return sl.range_by_rank(0, len(sl) - 1)


def check(sl, ref):
    """ref is a sorted list of (score, member). Verifies order, rank and get_by_rank."""
    assert len(sl) == len(ref)
    assert members(sl) == [(m, s) for s, m in ref]
    for i, (s, m) in enumerate(ref):
        assert sl.rank(s, m) == i
        node = sl.get_by_rank(i)
        assert (node.score, node.member) == (s, m)
    assert sl.get_by_rank(len(ref)) is None


def test_empty():
    sl = SkipList()
    check(sl, [])
    assert sl.rank(1.0, b"a") == -1
    assert sl.delete(1.0, b"a") is False


def test_insert_matches_sorted_order():
    rng = random.Random(1)
    sl, ref = SkipList(), set()
    while len(ref) < 500:
        item = (float(rng.randint(0, 50)), b"m%d" % rng.randint(0, 10_000))
        if item not in ref:
            ref.add(item)
            sl.insert(*item)
    check(sl, sorted(ref))


def test_same_score_ordered_by_member():
    sl = SkipList()
    for m in (b"c", b"a", b"b"):
        sl.insert(1.0, m)
    assert members(sl) == [(b"a", 1.0), (b"b", 1.0), (b"c", 1.0)]


def test_get_by_rank_bounds():
    sl = SkipList()
    for i in range(3):
        sl.insert(float(i), b"m%d" % i)
    assert sl.get_by_rank(-1) is None
    assert sl.get_by_rank(3) is None
    assert sl.get_by_rank(0).member == b"m0"
    assert sl.get_by_rank(2).member == b"m2"


def test_delete_missing():
    sl = SkipList()
    sl.insert(1.0, b"a")
    assert sl.delete(2.0, b"a") is False
    assert sl.delete(1.0, b"b") is False
    assert len(sl) == 1


def test_random_insert_delete_matches_reference():
    rng = random.Random(7)
    sl, ref = SkipList(), set()
    for step in range(3000):
        item = (float(rng.randint(0, 30)), b"m%d" % rng.randint(0, 200))
        if rng.random() < 0.6:
            if item not in ref:
                ref.add(item)
                sl.insert(*item)
        else:
            assert sl.delete(*item) == (item in ref)
            ref.discard(item)
        if step % 250 == 0:
            check(sl, sorted(ref))
    check(sl, sorted(ref))


def test_delete_everything_resets_levels():
    rng = random.Random(3)
    sl = SkipList()
    items = [(float(i), b"m%d" % i) for i in range(200)]
    for item in items:
        sl.insert(*item)
    rng.shuffle(items)
    for item in items:
        assert sl.delete(*item) is True
    assert len(sl) == 0
    assert sl.level == 1
    check(sl, [])

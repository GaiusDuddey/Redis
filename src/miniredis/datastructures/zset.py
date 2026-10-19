from miniredis.datastructures.skiplist import SkipList


class ZSet:
    """Sorted set: dict for O(1) member->score, skip list for ordered/rank queries."""

    def __init__(self) -> None:
        self._scores: dict[bytes, float] = {}
        self._sl = SkipList()

    def __len__(self) -> int:
        return len(self._scores)

    def add(self, member: bytes, score: float) -> bool:
        """Insert or update. Returns True if the member is new."""
        old = self._scores.get(member)
        if old is not None:
            if old != score:
                self._sl.delete(old, member)
                self._sl.insert(score, member)
                self._scores[member] = score
            return False
        self._sl.insert(score, member)
        self._scores[member] = score
        return True

    def remove(self, member: bytes) -> bool:
        score = self._scores.pop(member, None)
        if score is None:
            return False
        self._sl.delete(score, member)
        return True

    def score(self, member: bytes) -> float | None:
        return self._scores.get(member)

    def rank(self, member: bytes) -> int | None:
        score = self._scores.get(member)
        if score is None:
            return None
        return self._sl.rank(score, member)

    def range_by_rank(self, start: int, stop: int) -> list[tuple[bytes, float]]:
        return self._sl.range_by_rank(start, stop)

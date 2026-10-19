"""Skip list ordered by (score, member), with spans like Redis's zskiplist.

Each node has a random height. Level 0 links every node; higher levels skip ahead.
span[i] = how many level-0 steps the link at level i jumps, which is what makes
rank queries O(log n) instead of O(n).
"""
import random

MAX_LEVEL = 32
P = 0.25  # chance of promoting a node one level up


class Node:
    __slots__ = ("score", "member", "forward", "span")

    def __init__(self, level: int, score: float, member: bytes) -> None:
        self.score = score
        self.member = member
        self.forward: list = [None] * level
        self.span: list[int] = [0] * level


class SkipList:
    def __init__(self) -> None:
        self.header = Node(MAX_LEVEL, 0.0, b"")
        self.level = 1
        self.length = 0

    def __len__(self) -> int:
        return self.length

    @staticmethod
    def _random_level() -> int:
        level = 1
        while level < MAX_LEVEL and random.random() < P:
            level += 1
        return level

    def insert(self, score: float, member: bytes) -> None:
        """Caller guarantees this exact (score, member) is not already present."""
        update: list = [None] * MAX_LEVEL
        rank = [0] * MAX_LEVEL
        x = self.header
        for i in range(self.level - 1, -1, -1):
            rank[i] = 0 if i == self.level - 1 else rank[i + 1]
            while x.forward[i] is not None and (
                x.forward[i].score,
                x.forward[i].member,
            ) < (score, member):
                rank[i] += x.span[i]
                x = x.forward[i]
            update[i] = x

        level = self._random_level()
        if level > self.level:
            for i in range(self.level, level):
                rank[i] = 0
                update[i] = self.header
                update[i].span[i] = self.length
            self.level = level

        node = Node(level, score, member)
        for i in range(level):
            node.forward[i] = update[i].forward[i]
            update[i].forward[i] = node
            node.span[i] = update[i].span[i] - (rank[0] - rank[i])
            update[i].span[i] = (rank[0] - rank[i]) + 1
        for i in range(level, self.level):
            update[i].span[i] += 1
        self.length += 1

    def delete(self, score: float, member: bytes) -> bool:
        update: list = [None] * MAX_LEVEL
        x = self.header
        for i in range(self.level - 1, -1, -1):
            while x.forward[i] is not None and (
                x.forward[i].score,
                x.forward[i].member,
            ) < (score, member):
                x = x.forward[i]
            update[i] = x
        x = x.forward[0]
        if x is None or x.score != score or x.member != member:
            return False
        for i in range(self.level):
            if update[i].forward[i] is x:
                update[i].span[i] += x.span[i] - 1
                update[i].forward[i] = x.forward[i]
            else:
                update[i].span[i] -= 1
        while self.level > 1 and self.header.forward[self.level - 1] is None:
            self.level -= 1
        self.length -= 1
        return True

    def rank(self, score: float, member: bytes) -> int:
        """0-based position of (score, member), or -1 if absent."""
        r = 0
        x = self.header
        for i in range(self.level - 1, -1, -1):
            while x.forward[i] is not None and (
                x.forward[i].score,
                x.forward[i].member,
            ) <= (score, member):
                r += x.span[i]
                x = x.forward[i]
            if x is not self.header and x.score == score and x.member == member:
                return r - 1
        return -1

    def get_by_rank(self, rank: int) -> Node | None:
        """Node at 0-based position, or None."""
        if rank < 0 or rank >= self.length:
            return None
        target = rank + 1
        traversed = 0
        x = self.header
        for i in range(self.level - 1, -1, -1):
            while x.forward[i] is not None and traversed + x.span[i] <= target:
                traversed += x.span[i]
                x = x.forward[i]
            if traversed == target:
                return x
        return None

    def range_by_rank(self, start: int, stop: int) -> list[tuple[bytes, float]]:
        """(member, score) pairs for positions start..stop inclusive (0-based)."""
        out: list[tuple[bytes, float]] = []
        node = self.get_by_rank(start)
        remaining = stop - start + 1
        while node is not None and remaining > 0:
            out.append((node.member, node.score))
            node = node.forward[0]
            remaining -= 1
        return out

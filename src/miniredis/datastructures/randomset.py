import random


class RandomSet:
    """Set with O(1) add, discard and uniform random sampling.

    A list gives O(1) random access, a dict maps item -> list index so
    discard can swap the removed item with the last one in O(1)."""

    def __init__(self) -> None:
        self._items: list = []
        self._pos: dict = {}

    def __len__(self) -> int:
        return len(self._items)

    def __contains__(self, item) -> bool:
        return item in self._pos

    def __iter__(self):
        return iter(self._items)

    def add(self, item) -> None:
        if item in self._pos:
            return
        self._pos[item] = len(self._items)
        self._items.append(item)

    def discard(self, item) -> None:
        i = self._pos.pop(item, None)
        if i is None:
            return
        last = self._items.pop()
        if i < len(self._items):  # item was not the last one: fill its hole
            self._items[i] = last
            self._pos[last] = i

    def sample(self, k: int) -> list:
        if len(self._items) <= k:
            return list(self._items)
        return random.sample(self._items, k)

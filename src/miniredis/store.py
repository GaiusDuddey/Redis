"""Keyspace. Keys and values are bytes (binary-safe, like real Redis)."""


class Store:
    def __init__(self) -> None:
        self._data: dict[bytes, bytes] = {}

    def get(self, key: bytes) -> bytes | None:
        return self._data.get(key)

    def set(self, key: bytes, value: bytes) -> None:
        self._data[key] = value

    def delete(self, key: bytes) -> bool:
        return self._data.pop(key, None) is not None

    def exists(self, key: bytes) -> bool:
        return key in self._data

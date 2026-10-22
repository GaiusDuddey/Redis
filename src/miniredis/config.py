from dataclasses import dataclass


@dataclass
class PersistenceConfig:
    dir: str = "data"
    appendonly: bool = False
    appendfsync: str = "everysec"  # always | everysec | no
    snapshot_interval: float = 0  # seconds between automatic snapshots, 0 = off
    rewrite_min_size: int = 64 * 1024 * 1024  # AOF auto-rewrite only above this size

    @property
    def enabled(self) -> bool:
        return self.appendonly or self.snapshot_interval > 0

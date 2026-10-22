import os


class PersistenceError(Exception):
    """The AOF or snapshot on disk can't be loaded. The server refuses to start
    rather than silently coming up with missing data."""


def fsync_dir(path: str) -> None:
    """fsync a directory so a rename inside it survives a power cut."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass  # some filesystems (e.g. Windows drives mounted in WSL) don't support it
    finally:
        os.close(fd)

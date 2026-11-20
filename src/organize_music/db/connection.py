"""Connections and the exclusive writer lock for library.db.

One process owns the single write connection at a time. The lock is an
``fcntl.flock`` on ``state/writer.lock``: the server holds it for its lifetime
and CLI writers (``recover``, ``db migrate``) take the same lock and fail with
"server is running" when they cannot.
"""

import fcntl
import os
import sqlite3
from pathlib import Path


class WriterBusy(Exception):
    """Raised when the exclusive writer lock is already held by another process."""


def open_writer(path: Path) -> sqlite3.Connection:
    """Open library.db for writing: WAL, durable commits, foreign keys on."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=FULL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def open_reader(path: Path) -> sqlite3.Connection:
    """Open library.db for read-only use; queries only, foreign keys on."""
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA query_only=ON")
    return conn


class WriterLock:
    """A context manager holding an exclusive, non-blocking lock on a file.

    A second lock on the same path while the first is held raises
    ``WriterBusy``; the lock is released when the ``with`` block exits.
    """

    def __init__(self, lock_path: Path) -> None:
        self._lock_path = lock_path
        self._fd: int | None = None

    def __enter__(self) -> "WriterLock":
        fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise WriterBusy("server is running") from None
        self._fd = fd
        return self

    def __exit__(self, *exc: object) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None

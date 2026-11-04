"""The `hashes` table: MD5 per file, valid while the file's size and mtime are unchanged."""

import sqlite3
from collections.abc import Set
from datetime import UTC, datetime
from pathlib import Path

from organize_music.models import FileRecord

HASHES_SCHEMA = """
CREATE TABLE IF NOT EXISTS hashes (
    root TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    md5 TEXT NOT NULL,
    hashed_at TEXT NOT NULL,
    PRIMARY KEY (root, path)
)
"""
_SELECT = "SELECT md5 FROM hashes WHERE root = ? AND path = ? AND size = ? AND mtime_ns = ?"
_INSERT = "INSERT OR REPLACE INTO hashes VALUES (?, ?, ?, ?, ?, ?)"


class HashIndex:
    """Repository for file hashes, sharing the index connection."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def get(self, root: Path, record: FileRecord) -> str | None:
        key = (str(root), str(record.path), record.size, record.mtime_ns)
        row = self._conn.execute(_SELECT, key).fetchone()
        return row[0] if row else None

    def put(self, root: Path, record: FileRecord, md5: str) -> None:
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        row = (str(root), str(record.path), record.size, record.mtime_ns, md5, stamp)
        self._conn.execute(_INSERT, row)

    def all(self, root: Path) -> dict[Path, str]:
        rows = self._conn.execute("SELECT path, md5 FROM hashes WHERE root = ?", (str(root),))
        return {Path(path): md5 for path, md5 in rows}

    def prune(self, root: Path, keep: Set[Path]) -> int:
        """Delete hashes under root whose path is not in keep. Returns rows removed."""
        stale = [(str(root), str(p)) for p in self.all(root) if p not in keep]
        self._conn.executemany("DELETE FROM hashes WHERE root = ? AND path = ?", stale)
        return len(stale)

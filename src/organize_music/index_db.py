"""SQLite repository for indexed tracks. Lives outside the library.

Each row caches the *raw* read (tags JSON or the read error), so interpretation
rules can change without re-reading files from disk. Interpreted fields are
stored alongside for querying (reports, future web UI) and refreshed every run.
The index is a cache: an incompatible schema is dropped and rebuilt.
"""

import json
import sqlite3
from collections.abc import Iterator, Set
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from organize_music.models import (
    FIELD_NAMES,
    Field,
    FileRecord,
    RawTags,
    ReadFailure,
    ReadResult,
    TrackMetadata,
)

SCHEMA_VERSION = 2

_KEY_COLUMNS = ["root", "path", "size", "mtime_ns", "ext"]
_RAW_COLUMNS = ["raw_tags", "read_error", "duration_seconds", "bitrate_kbps"]
_FIELD_COLUMNS = [col for name in FIELD_NAMES for col in (name, f"{name}_src")]
_COLUMNS = [*_KEY_COLUMNS, *_RAW_COLUMNS, *_FIELD_COLUMNS, "indexed_at"]
# Field value columns have no declared type so SQLite keeps ints and strings as-is.
_FIELD_DDL = ",\n    ".join(f"{name}, {name}_src TEXT NOT NULL" for name in FIELD_NAMES)
_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS tracks (
    root TEXT NOT NULL,
    path TEXT NOT NULL,
    size INTEGER NOT NULL,
    mtime_ns INTEGER NOT NULL,
    ext TEXT NOT NULL,
    raw_tags TEXT,
    read_error TEXT,
    duration_seconds REAL,
    bitrate_kbps INTEGER,
    {_FIELD_DDL},
    indexed_at TEXT NOT NULL,
    PRIMARY KEY (root, path)
)
"""
_INSERT = (
    f"INSERT OR REPLACE INTO tracks ({', '.join(_COLUMNS)}) "
    f"VALUES ({', '.join('?' for _ in _COLUMNS)})"
)
_SELECT_RAW = (
    f"SELECT {', '.join(_RAW_COLUMNS)} FROM tracks "
    "WHERE root = ? AND path = ? AND size = ? AND mtime_ns = ?"
)


def _raw_values(result: ReadResult) -> list[object]:
    if isinstance(result, ReadFailure):
        return [None, result.error, None, None]
    tags = json.dumps(dict(result.tags), ensure_ascii=False, sort_keys=True)
    return [tags, None, result.duration_seconds, result.bitrate_kbps]


def _field_values(track: TrackMetadata) -> list[object]:
    values: list[object] = []
    for name in FIELD_NAMES:
        field: Field = getattr(track, name)
        values += [field.value, field.source.value]
    return values


def _from_raw_row(row: sqlite3.Row) -> ReadResult:
    if row["read_error"] is not None:
        return ReadFailure(error=row["read_error"])
    return RawTags(
        tags=json.loads(row["raw_tags"]),
        duration_seconds=row["duration_seconds"],
        bitrate_kbps=row["bitrate_kbps"],
    )


def _prepare(conn: sqlite3.Connection) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
        conn.execute("DROP TABLE IF EXISTS tracks")
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.execute(_SCHEMA)


class IndexDB:
    """Repository over one SQLite file. Rows are keyed by (library root, relative path)."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    @classmethod
    @contextmanager
    def open(cls, path: Path) -> Iterator["IndexDB"]:
        """Open (creating if needed). Always commits and closes on exit, even on Ctrl-C."""
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
        try:
            _prepare(conn)
            yield cls(conn)
        finally:
            conn.commit()
            conn.close()

    def get(self, root: Path, record: FileRecord) -> ReadResult | None:
        """Cached raw read, or None if absent or the file's size/mtime changed."""
        key = (str(root), str(record.path), record.size, record.mtime_ns)
        row = self._conn.execute(_SELECT_RAW, key).fetchone()
        return _from_raw_row(row) if row else None

    def upsert(self, root: Path, track: TrackMetadata, result: ReadResult) -> None:
        rec = track.record
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        values = [str(root), str(rec.path), rec.size, rec.mtime_ns, rec.ext]
        values += [*_raw_values(result), *_field_values(track), stamp]
        self._conn.execute(_INSERT, values)

    def count(self, root: Path) -> int:
        sql = "SELECT COUNT(*) FROM tracks WHERE root = ?"
        return self._conn.execute(sql, (str(root),)).fetchone()[0]

    def prune(self, root: Path, keep: Set[Path]) -> int:
        """Delete rows under root whose path is not in keep. Returns rows removed."""
        keep_str = {str(p) for p in keep}
        rows = self._conn.execute("SELECT path FROM tracks WHERE root = ?", (str(root),))
        stale = [(str(root), r["path"]) for r in rows if r["path"] not in keep_str]
        self._conn.executemany("DELETE FROM tracks WHERE root = ? AND path = ?", stale)
        return len(stale)

    def commit(self) -> None:
        self._conn.commit()

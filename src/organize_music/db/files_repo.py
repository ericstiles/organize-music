"""Typed reader/writer over the ``files`` table of library.db (PLAN §5).

``FilesRepo`` gives the web page and the move op typed access to scanned files.
``insert_scanned`` records a freshly discovered file as status ``'present'`` with
every metadata ``*_src`` left ``'missing'`` and ``path_key`` computed by
``paths.path_key``; ``get``, ``get_by_key``, ``page`` and ``count`` read it back.
The repository commits nothing: the caller owns the transaction.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from organize_music.models import FileRecord
from organize_music.paths import path_key

# Every metadata field stored with a provenance column. A freshly scanned row
# carries no interpreted value, so each ``*_src`` is left 'missing'.
_MISSING_SOURCES = (
    "artist_src",
    "album_artist_src",
    "album_src",
    "title_src",
    "track_number_src",
    "disc_number_src",
    "year_src",
    "genre_src",
)
# Interpreted tag columns; absent on a fresh scan (read later, P1-9 updates them).
_TAG_COLUMNS = (
    "artist",
    "album_artist",
    "album",
    "title",
    "track_number",
    "disc_number",
    "year",
    "genre",
)
# Hash bookkeeping: a fresh scan has computed nothing yet.
_HASH_COLUMNS = ("audio_hash", "hash_kind", "hash_size", "hash_mtime_ns")
# Raw read bookkeeping: not read until hashing; NULL on a fresh scan.
_RAW_COLUMNS = ("raw_tags", "read_error", "duration_seconds", "bitrate_kbps")


@dataclass(frozen=True)
class FileRow:
    """One row of the ``files`` table, as the web page and move op consume it."""

    file_id: int
    path: str | None
    path_key: str | None
    last_path: str
    status: str
    kind: str
    size: int
    mtime_ns: int
    ext: str
    row_version: int
    artist: str | int | None
    album: str | int | None
    title: str | int | None
    track_number: str | int | None


class FilesRepo:
    """Typed access to the ``files`` table; the caller owns the transaction."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_scanned(self, rec: FileRecord, kind: str, now: str) -> int:
        """Insert a freshly scanned file and return its new ``file_id``.

        The row is status ``'present'``; ``path_key`` is ``paths.path_key`` of
        the file's relative path (so the exFAT unique index collides on
        case-only variants); every metadata ``*_src`` is ``'missing'`` and every
        interpreted tag column is NULL. The caller commits.
        """
        rel = str(rec.path)
        key = path_key(rel)
        params: dict[str, object] = {
            "path": rel,
            "path_key": key,
            "last_path": rel,
            "status": "present",
            "kind": kind,
            "size": rec.size,
            "mtime_ns": rec.mtime_ns,
            "ext": rec.ext,
            "first_seen_at": now,
            "updated_at": now,
        }
        for col in _MISSING_SOURCES:
            params[col] = "missing"
        for col in _TAG_COLUMNS + _HASH_COLUMNS + _RAW_COLUMNS:
            params[col] = None
        cols = ", ".join(params)
        placeholders = ", ".join("?" for _ in params)
        cur = self._conn.execute(
            f"INSERT INTO files ({cols}) VALUES ({placeholders})", list(params.values())
        )
        return int(cur.lastrowid)

    def get(self, file_id: int) -> FileRow | None:
        """Return the row with ``file_id``, or None when no such row exists."""
        row = self._conn.execute(_SELECT + " WHERE file_id = ?", (file_id,)).fetchone()
        return _to_row(row) if row is not None else None

    def get_by_key(self, key: str) -> FileRow | None:
        """Return the row whose ``path_key`` equals ``key``, or None."""
        row = self._conn.execute(_SELECT + " WHERE path_key = ?", (key,)).fetchone()
        return _to_row(row) if row is not None else None

    def page(self, offset: int, limit: int) -> list[FileRow]:
        """Return the page of rows at ``offset``/``limit`` ordered by path_key, file_id."""
        rows = self._conn.execute(
            _SELECT + " ORDER BY path_key, file_id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [_to_row(r) for r in rows]

    def count(self) -> int:
        """Number of rows in ``files``."""
        return int(self._conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])

    def commit(self) -> None:
        """Commit the caller's open transaction (e.g. a scan finishing its inserts)."""
        self._conn.commit()


# The columns FileRow projects, in dataclass order (so a row maps positionally).
_SELECT = (
    "SELECT file_id, path, path_key, last_path, status, kind, size, mtime_ns, "
    "ext, row_version, artist, album, title, track_number FROM files"
)


def _to_row(row: sqlite3.Row) -> FileRow:
    """Map a ``files`` row to a :class:`FileRow` (projected columns, in order)."""
    return FileRow(
        file_id=row["file_id"],
        path=row["path"],
        path_key=row["path_key"],
        last_path=row["last_path"],
        status=row["status"],
        kind=row["kind"],
        size=row["size"],
        mtime_ns=row["mtime_ns"],
        ext=row["ext"],
        row_version=row["row_version"],
        artist=row["artist"],
        album=row["album"],
        title=row["title"],
        track_number=row["track_number"],
    )

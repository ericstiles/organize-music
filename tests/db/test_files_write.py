"""Tests for the compare-and-set path update (PLAN §6.2, issue b8p.14).

``files_write.update_path`` performs the committed move's row update: it sets
``path``, ``path_key``, ``last_path``, ``size``, ``mtime_ns`` and ``updated_at``
and bumps ``row_version`` by one, but only when the row's ``row_version`` still
equals the caller's expectation and the row is ``'present'``. A mismatch or a
``'missing'``/``'gone'`` row leaves the row untouched and raises
:class:`StaleRow`; a ``path_key`` that collides with another row raises
:class:`PathTaken`. The function commits nothing: the caller wraps it with the
op state change in one transaction.
"""

import sqlite3
from pathlib import Path

import pytest

from organize_music.db import migrate
from organize_music.db.files_repo import FilesRepo
from organize_music.db.files_write import PathTaken, StaleRow, update_path
from organize_music.models import FileRecord
from organize_music.paths import path_key


def open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrated(tmp_path: Path) -> sqlite3.Connection:
    """A fresh, migrated library.db (version 1) with a writer connection."""
    path = tmp_path / "library.db"
    conn = open_conn(path)
    migrate(conn, path, tmp_path / "backups", "2026-01-01T00:00:00Z")
    return conn


def record(name: str, **overrides: object) -> FileRecord:
    vals: dict[str, object] = {"path": name, "size": 1024, "mtime_ns": 1_700, "ext": "mp3"}
    vals.update(overrides)
    return FileRecord(**vals)


def insert(conn: sqlite3.Connection, name: str) -> int:
    return FilesRepo(conn).insert_scanned(record(name), "audio", "2026-01-01T00:00:00Z")


def row_state(conn: sqlite3.Connection, file_id: int) -> tuple[str, int, int]:
    """Return (path, row_version, size) for a file row."""
    r = conn.execute(
        "SELECT path, row_version, size FROM files WHERE file_id = ?", (file_id,)
    ).fetchone()
    return r["path"], int(r["row_version"]), int(r["size"])


def test_update_path_happy_path_bumps_row_version_and_key(tmp_path: Path):
    conn = migrated(tmp_path)
    fid = insert(conn, "artist/album/01 Song.mp3")
    assert row_state(conn, fid) == ("artist/album/01 Song.mp3", 1, 1024)

    update_path(conn, fid, 1, "albums/Artist/01 Song.mp3", 2048, 5_000, "2026-02-01T00:00:00Z")

    r = conn.execute("SELECT * FROM files WHERE file_id = ?", (fid,)).fetchone()
    assert r["path"] == "albums/Artist/01 Song.mp3"
    assert r["path_key"] == path_key("albums/Artist/01 Song.mp3")
    assert r["last_path"] == "albums/Artist/01 Song.mp3"
    assert int(r["size"]) == 2048
    assert int(r["mtime_ns"]) == 5_000
    assert int(r["row_version"]) == 2
    assert r["updated_at"] == "2026-02-01T00:00:00Z"
    assert r["status"] == "present"


def test_update_path_does_not_commit(tmp_path: Path):
    # The caller owns the transaction: update_path must leave the change
    # uncommitted, so a second connection reading library.db sees no update.
    conn = migrated(tmp_path)
    fid = insert(conn, "a/one.mp3")
    conn.commit()

    update_path(conn, fid, 1, "b/one.mp3", 4096, 7_000, "2026-03-01T00:00:00Z")

    other = open_conn(tmp_path / "library.db")
    r = other.execute("SELECT path, row_version FROM files WHERE file_id = ?", (fid,)).fetchone()
    assert r["path"] == "a/one.mp3"
    assert int(r["row_version"]) == 1


def test_update_path_wrong_row_version_raises_stale_and_leaves_row_unchanged(tmp_path: Path):
    conn = migrated(tmp_path)
    fid = insert(conn, "a/one.mp3")

    with pytest.raises(StaleRow):
        update_path(conn, fid, 999, "b/one.mp3", 2048, 5_000, "2026-02-01T00:00:00Z")

    assert row_state(conn, fid) == ("a/one.mp3", 1, 1024)


def test_update_path_missing_status_raises_stale_and_leaves_row_unchanged(tmp_path: Path):
    conn = migrated(tmp_path)
    fid = insert(conn, "a/one.mp3")
    # A 'missing' row no longer matches status='present'; the compare-and-set
    # must refuse it as stale without touching the row.
    conn.execute("UPDATE files SET status = 'missing' WHERE file_id = ?", (fid,))
    conn.commit()

    with pytest.raises(StaleRow):
        update_path(conn, fid, 1, "b/one.mp3", 2048, 5_000, "2026-02-01T00:00:00Z")

    assert row_state(conn, fid) == ("a/one.mp3", 1, 1024)


def test_update_path_path_key_collision_raises_path_taken_and_leaves_row_unchanged(tmp_path: Path):
    # exFAT collision: the new path's key already belongs to another row, so the
    # partial unique index must reject the update and leave the row untouched.
    conn = migrated(tmp_path)
    fid = insert(conn, "a/one.mp3")
    insert(conn, "b/two.mp3")

    with pytest.raises(PathTaken):
        update_path(conn, fid, 1, "B/TWO.MP3", 2048, 5_000, "2026-02-01T00:00:00Z")

    assert row_state(conn, fid) == ("a/one.mp3", 1, 1024)

"""Tests for the files repository (PLAN §5, issue b8p.13).

FilesRepo is the typed reader/writer over the ``files`` table of library.db.
``insert_scanned`` records a freshly discovered file (status 'present', every
metadata ``*_src`` 'missing', ``path_key`` via ``paths.path_key``); ``get``,
``get_by_key``, ``page`` and ``count`` read it back. The caller owns the
transaction, so the repository commits nothing.
"""

import sqlite3
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from organize_music.db import migrate
from organize_music.db.files_repo import FilesRepo
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


def test_insert_then_get_round_trips(tmp_path: Path):
    conn = migrated(tmp_path)
    repo = FilesRepo(conn)
    fid = repo.insert_scanned(record("artist/album/01 Song.mp3"), "audio", "2026-01-01T00:00:00Z")
    row = repo.get(fid)
    assert row is not None
    assert row.file_id == fid
    assert row.path == "artist/album/01 Song.mp3"
    assert row.path_key == path_key("artist/album/01 Song.mp3")
    assert row.last_path == "artist/album/01 Song.mp3"
    assert row.status == "present"
    assert row.kind == "audio"
    assert row.size == 1024
    assert row.mtime_ns == 1_700
    assert row.ext == "mp3"
    assert row.row_version == 1
    # A freshly scanned row carries no interpreted metadata yet.
    assert row.artist is None
    assert row.album is None
    assert row.title is None
    assert row.track_number is None


def test_insert_sets_all_sources_to_missing(tmp_path: Path):
    conn = migrated(tmp_path)
    repo = FilesRepo(conn)
    fid = repo.insert_scanned(record("a/b.mp3"), "audio", "2026-01-01T00:00:00Z")
    row = conn.execute("SELECT * FROM files WHERE file_id = ?", (fid,)).fetchone()
    for col in (
        "artist_src",
        "album_artist_src",
        "album_src",
        "title_src",
        "track_number_src",
        "disc_number_src",
        "year_src",
        "genre_src",
    ):
        assert row[col] == "missing"


def test_get_missing_file_id_returns_none(tmp_path: Path):
    conn = migrated(tmp_path)
    repo = FilesRepo(conn)
    assert repo.get(999) is None


def test_get_by_key_round_trips(tmp_path: Path):
    conn = migrated(tmp_path)
    repo = FilesRepo(conn)
    repo.insert_scanned(record("artist/album/01 Song.mp3"), "audio", "2026-01-01T00:00:00Z")
    key = path_key("artist/album/01 Song.mp3")
    row = repo.get_by_key(key)
    assert row is not None
    assert row.path == "artist/album/01 Song.mp3"
    assert repo.get_by_key(path_key("nope.mp3")) is None


def test_inserting_case_variants_raises_integrity_error(tmp_path: Path):
    # exFAT collision: 'A.mp3' and 'a.mp3' share a path_key; the unique
    # index on path_key must reject the second insert.
    conn = migrated(tmp_path)
    repo = FilesRepo(conn)
    repo.insert_scanned(record("A.mp3"), "audio", "2026-01-01T00:00:00Z")
    with pytest.raises(sqlite3.IntegrityError):
        repo.insert_scanned(record("a.mp3"), "audio", "2026-01-01T00:00:00Z")


def test_page_returns_first_rows_by_path_key(tmp_path: Path):
    conn = migrated(tmp_path)
    repo = FilesRepo(conn)
    for name in ("zeta/z.mp3", "alpha/a.mp3", "mid/m.mp3"):
        repo.insert_scanned(record(name), "audio", "2026-01-01T00:00:00Z")
    page = repo.page(0, 2)
    assert [r.path for r in page] == ["alpha/a.mp3", "mid/m.mp3"]
    # The next page continues the ordering.
    assert [r.path for r in repo.page(2, 2)] == ["zeta/z.mp3"]
    assert repo.page(9, 2) == []


def test_count(tmp_path: Path):
    conn = migrated(tmp_path)
    repo = FilesRepo(conn)
    assert repo.count() == 0
    repo.insert_scanned(record("a.mp3"), "audio", "2026-01-01T00:00:00Z")
    repo.insert_scanned(record("b.mp3"), "audio", "2026-01-01T00:00:00Z")
    assert repo.count() == 2


def test_file_row_is_frozen(tmp_path: Path):
    conn = migrated(tmp_path)
    repo = FilesRepo(conn)
    fid = repo.insert_scanned(record("a.mp3"), "audio", "2026-01-01T00:00:00Z")
    row = repo.get(fid)
    with pytest.raises(FrozenInstanceError):
        row.file_id = 0  # type: ignore[misc]

"""Tests for the SQLite index repository (caches raw reads, stores interpreted rows)."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path

import pytest

from organize_music.index_db import SCHEMA_VERSION, IndexDB
from organize_music.metadata import interpret
from organize_music.models import FileRecord, RawTags, ReadFailure, ReadResult

ROOT = Path("/music")
RAW = RawTags(
    tags={"artist": "Prince", "title": "Purple Rain", "tracknumber": "3", "date": "1984"},
    duration_seconds=520.5,
    bitrate_kbps=256,
)


def rec(name: str = "A/B/01.mp3", size: int = 100, mtime_ns: int = 5) -> FileRecord:
    return FileRecord(path=Path(name), size=size, mtime_ns=mtime_ns, ext="mp3")


def store(db: IndexDB, record: FileRecord, result: ReadResult = RAW, root: Path = ROOT) -> None:
    db.upsert(root, interpret(record, result), result)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[IndexDB]:
    with IndexDB.open(tmp_path / "state" / "index.db") as index:
        yield index


def test_open_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "a" / "b" / "index.db"

    with IndexDB.open(path):
        pass

    assert path.exists()


def test_raw_read_round_trips_exactly(db: IndexDB) -> None:
    store(db, rec())

    assert db.get(ROOT, rec()) == RAW


def test_read_failure_round_trips(db: IndexDB) -> None:
    failure = ReadFailure(error="bad frame")
    store(db, rec("broken.mp3"), failure)

    assert db.get(ROOT, rec("broken.mp3")) == failure


def test_interpreted_columns_are_queryable(db: IndexDB, tmp_path: Path) -> None:
    store(db, rec("loose.mp3"))  # loose file: no folder fallback, so album stays missing
    db.commit()

    with closing(sqlite3.connect(tmp_path / "state" / "index.db")) as conn:
        row = conn.execute(
            "SELECT artist, artist_src, track_number, album_src FROM tracks"
        ).fetchone()
    assert row == ("Prince", "tag", 3, "missing")


def test_get_returns_none_when_size_or_mtime_changed(db: IndexDB) -> None:
    store(db, rec())

    assert db.get(ROOT, rec(size=101)) is None
    assert db.get(ROOT, rec(mtime_ns=6)) is None
    assert db.get(ROOT, rec("missing.mp3")) is None


def test_upsert_replaces_existing_row(db: IndexDB) -> None:
    store(db, rec())
    store(db, rec(size=200))

    assert db.get(ROOT, rec(size=200)) == RAW
    assert db.count(ROOT) == 1


def test_roots_are_isolated(db: IndexDB) -> None:
    store(db, rec())

    assert db.get(Path("/other"), rec()) is None
    assert db.count(Path("/other")) == 0


def test_prune_removes_rows_for_files_no_longer_present(db: IndexDB) -> None:
    store(db, rec("keep.mp3"))
    store(db, rec("gone.mp3"))
    store(db, rec("gone.mp3"), root=Path("/other"))

    removed = db.prune(ROOT, {Path("keep.mp3")})

    assert removed == 1
    assert db.count(ROOT) == 1
    assert db.count(Path("/other")) == 1


def test_close_without_commit_still_persists(tmp_path: Path) -> None:
    path = tmp_path / "index.db"
    with IndexDB.open(path) as first:
        store(first, rec())

    with IndexDB.open(path) as second:
        assert second.count(ROOT) == 1


def test_old_schema_is_rebuilt_because_index_is_only_a_cache(tmp_path: Path) -> None:
    path = tmp_path / "index.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE TABLE tracks (root TEXT, path TEXT)")
        conn.execute("INSERT INTO tracks VALUES ('/music', 'old.mp3')")
        conn.execute("PRAGMA user_version = 1")
        conn.commit()

    with IndexDB.open(path) as db:
        assert db.count(ROOT) == 0
        store(db, rec())
        assert db.get(ROOT, rec()) == RAW

    with closing(sqlite3.connect(path)) as conn:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == SCHEMA_VERSION

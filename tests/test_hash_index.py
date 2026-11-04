"""Tests for the hashes table in the SQLite index."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from organize_music.index_db import IndexDB
from organize_music.models import FileRecord

ROOT = Path("/music")


def rec(name: str = "a.mp3", size: int = 100, mtime_ns: int = 5) -> FileRecord:
    return FileRecord(path=Path(name), size=size, mtime_ns=mtime_ns, ext="mp3")


@pytest.fixture
def db(tmp_path: Path) -> Iterator[IndexDB]:
    with IndexDB.open(tmp_path / "index.db") as index:
        yield index


def test_put_then_get(db: IndexDB) -> None:
    db.hashes.put(ROOT, rec(), "abc")

    assert db.hashes.get(ROOT, rec()) == "abc"


def test_get_is_none_when_file_changed_or_unknown(db: IndexDB) -> None:
    db.hashes.put(ROOT, rec(), "abc")

    assert db.hashes.get(ROOT, rec(size=101)) is None
    assert db.hashes.get(ROOT, rec(mtime_ns=6)) is None
    assert db.hashes.get(ROOT, rec("other.mp3")) is None
    assert db.hashes.get(Path("/elsewhere"), rec()) is None


def test_put_replaces(db: IndexDB) -> None:
    db.hashes.put(ROOT, rec(), "abc")
    db.hashes.put(ROOT, rec(size=200), "def")

    assert db.hashes.get(ROOT, rec(size=200)) == "def"
    assert db.hashes.all(ROOT) == {Path("a.mp3"): "def"}


def test_prune_removes_paths_not_kept(db: IndexDB) -> None:
    db.hashes.put(ROOT, rec("keep.mp3"), "a")
    db.hashes.put(ROOT, rec("gone.mp3"), "b")
    db.hashes.put(Path("/other"), rec("gone.mp3"), "b")

    assert db.hashes.prune(ROOT, {Path("keep.mp3")}) == 1
    assert db.hashes.all(ROOT) == {Path("keep.mp3"): "a"}
    assert db.hashes.all(Path("/other")) == {Path("gone.mp3"): "b"}


def test_hashes_persist_across_connections(tmp_path: Path) -> None:
    path = tmp_path / "index.db"
    with IndexDB.open(path) as first:
        first.hashes.put(ROOT, rec(), "abc")

    with IndexDB.open(path) as second:
        assert second.hashes.get(ROOT, rec()) == "abc"

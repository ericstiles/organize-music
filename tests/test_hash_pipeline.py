"""Tests for resumable MD5 collection over size-collision candidates."""

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from organize_music import hash_pipeline
from organize_music.index_db import IndexDB
from organize_music.scanner import walk_library

ORIGINAL = Path("Carbon Leaf/Echo Echo/01 Learn To Fly.mp3")
COPY = Path("ipod_favs/Learn To Fly.mp3")


@pytest.fixture
def dup_library(library: Path) -> Path:
    """The shared library plus one byte-identical copy in another folder."""
    (library / COPY).parent.mkdir(parents=True)
    shutil.copyfile(library / ORIGINAL, library / COPY)
    return library


@pytest.fixture
def db(tmp_path: Path) -> Iterator[IndexDB]:
    with IndexDB.open(tmp_path / "index.db") as index:
        yield index


def run(root: Path, db: IndexDB, rehash: bool = False) -> hash_pipeline.HashRun:
    records = list(walk_library(root))
    return hash_pipeline.collect_hashes(root, records, db, lambda _m: None, rehash=rehash)


def test_first_run_hashes_only_size_collisions(dup_library: Path, db: IndexDB) -> None:
    result = run(dup_library, db)

    assert result.candidates == 2
    assert (result.hashed, result.cached, result.failed) == (2, 0, 0)
    assert result.bytes_hashed == 2 * (dup_library / ORIGINAL).stat().st_size
    assert [paths for _md5, paths in result.groups] == [[ORIGINAL, COPY]]


def test_second_run_uses_cache(dup_library: Path, db: IndexDB) -> None:
    run(dup_library, db)

    result = run(dup_library, db)

    assert (result.hashed, result.cached, result.bytes_hashed) == (0, 2, 0)
    assert len(result.groups) == 1


def test_rehash_ignores_cache(dup_library: Path, db: IndexDB) -> None:
    run(dup_library, db)

    assert run(dup_library, db, rehash=True).hashed == 2


def test_changed_file_is_rehashed_and_no_longer_a_duplicate(dup_library: Path, db: IndexDB) -> None:
    run(dup_library, db)
    target = dup_library / COPY
    data = bytearray(target.read_bytes())
    data[-1] ^= 0xFF  # same size, different content
    target.write_bytes(bytes(data))
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    result = run(dup_library, db)

    assert (result.hashed, result.cached) == (1, 1)
    assert result.groups == ()


def test_files_no_longer_candidates_are_pruned(dup_library: Path, db: IndexDB) -> None:
    run(dup_library, db)
    (dup_library / COPY).unlink()

    result = run(dup_library, db)

    assert result.candidates == 0
    assert result.pruned == 2
    assert db.hashes.all(dup_library.resolve()) == {}


def test_unreadable_file_is_counted_and_skipped(
    dup_library: Path, db: IndexDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = hash_pipeline.md5_file

    def flaky(path: Path) -> str:
        if path.name == COPY.name:
            raise hash_pipeline.HashError("PermissionError: denied")
        return real(path)

    monkeypatch.setattr(hash_pipeline, "md5_file", flaky)

    result = run(dup_library, db)

    assert (result.hashed, result.failed) == (1, 1)
    assert result.failures == ((COPY, "PermissionError: denied"),)
    assert result.groups == ()


def test_interrupt_keeps_committed_progress(
    dup_library: Path, db: IndexDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    real = hash_pipeline.md5_file

    def interrupt_second(path: Path) -> str:
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt
        return real(path)

    monkeypatch.setattr(hash_pipeline, "md5_file", interrupt_second)
    monkeypatch.setattr(hash_pipeline, "COMMIT_EVERY", 1)

    with pytest.raises(KeyboardInterrupt):
        run(dup_library, db)

    assert len(db.hashes.all(dup_library)) == 1


def test_progress_reports_rate(
    dup_library: Path, db: IndexDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages: list[str] = []
    monkeypatch.setattr(hash_pipeline, "PROGRESS_EVERY", 1)
    records = list(walk_library(dup_library))

    hash_pipeline.collect_hashes(dup_library, records, db, messages.append)

    assert messages[0].startswith("  1/2 (hashed 1, cached 0, failed 0;")
    assert "MB/s" in messages[0]

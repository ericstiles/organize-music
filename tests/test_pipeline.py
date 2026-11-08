"""Tests for the resumable metadata pipeline (walk -> cache-or-read -> index)."""

import os
from pathlib import Path

import pytest

from organize_music import pipeline
from organize_music.index_db import IndexDB
from organize_music.models import Source
from organize_music.scanner import walk_library


def run(library: Path, db: IndexDB) -> pipeline.MetaRun:
    return pipeline.collect_metadata(library, list(walk_library(library)), db, lambda _m: None)


@pytest.fixture
def db(tmp_path: Path) -> IndexDB:
    with IndexDB.open(tmp_path / "index.db") as index:
        yield index


def test_first_run_reads_every_audio_file(library: Path, db: IndexDB) -> None:
    result = run(library, db)

    assert (result.read, result.cached, result.pruned) == (4, 0, 0)
    assert len(result.tracks) == 4
    assert db.count(library) == 4


def test_second_run_uses_cache(library: Path, db: IndexDB) -> None:
    first = run(library, db)

    second = run(library, db)

    assert (second.read, second.cached) == (0, 4)
    assert second.tracks == first.tracks


def test_changed_file_is_reread(library: Path, db: IndexDB) -> None:
    run(library, db)
    target = library / "01 Billie Jean.MP3"
    stat = target.stat()
    os.utime(target, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    result = run(library, db)

    assert (result.read, result.cached) == (1, 3)


def test_deleted_file_is_pruned(library: Path, db: IndexDB) -> None:
    run(library, db)
    (library / "01 Billie Jean.MP3").unlink()

    result = run(library, db)

    assert result.pruned == 1
    assert db.count(library) == 3


def test_interrupt_keeps_committed_progress(
    library: Path, db: IndexDB, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}
    real = pipeline.read_tags

    def flaky(path: Path) -> object:
        calls["n"] += 1
        if calls["n"] == 3:
            raise KeyboardInterrupt
        return real(path)

    monkeypatch.setattr(pipeline, "read_tags", flaky)
    monkeypatch.setattr(pipeline, "COMMIT_EVERY", 1)

    with pytest.raises(KeyboardInterrupt):
        run(library, db)

    assert db.count(library) == 2


def test_progress_messages(library: Path, db: IndexDB, monkeypatch: pytest.MonkeyPatch) -> None:
    messages: list[str] = []
    monkeypatch.setattr(pipeline, "PROGRESS_EVERY", 2)

    pipeline.collect_metadata(library, list(walk_library(library)), db, messages.append)

    assert "  2/4 (read 2, cached 0)" in messages


def test_collect_metadata_passes_skip_folders(library: Path, db: IndexDB) -> None:
    import shutil

    skip_dir = library / "Music2" / "Carbon Leaf"
    skip_dir.mkdir(parents=True)
    shutil.copyfile(
        library / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3", skip_dir / "99 Untagged.mp3"
    )
    records = list(walk_library(library))

    run = pipeline.collect_metadata(
        library, records, db, lambda _m: None, skip_folders=frozenset({"Music2"})
    )

    skipped = next(t for t in run.tracks if t.record.path.parts[0] == "Music2")
    assert skipped.artist.source is not Source.FOLDER

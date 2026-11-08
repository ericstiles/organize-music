"""Tests for the read-only library walker."""

from pathlib import Path

import pytest

from organize_music.scanner import LibraryNotFoundError, walk_library


def test_walk_returns_every_file_relative_and_sorted(library: Path) -> None:
    records = list(walk_library(library))

    assert [str(r.path) for r in records] == [
        "01 Billie Jean.MP3",
        "Carbon Leaf/Echo Echo/01 Learn To Fly.mp3",
        "Jay-Z/The Blueprint/02 Takeover.m4a",
        "broken.mp3",
        "cover.jpg",
    ]


def test_walk_lowercases_extension_and_records_size(library: Path) -> None:
    by_name = {r.path.name: r for r in walk_library(library)}

    assert by_name["01 Billie Jean.MP3"].ext == "mp3"
    assert by_name["broken.mp3"].size == 0
    assert by_name["cover.jpg"].mtime_ns > 0


def test_walk_fails_fast_when_root_missing(tmp_path: Path) -> None:
    with pytest.raises(LibraryNotFoundError, match="does not exist"):
        list(walk_library(tmp_path / "nope"))


def test_walk_fails_fast_when_root_empty(tmp_path: Path) -> None:
    with pytest.raises(LibraryNotFoundError, match="empty"):
        list(walk_library(tmp_path))


def test_walk_skips_symlinked_directories(library: Path) -> None:
    (library / "loop").symlink_to(library, target_is_directory=True)

    assert len(list(walk_library(library))) == 5


def test_walk_fails_fast_when_root_is_a_file(tmp_path: Path) -> None:
    file_root = tmp_path / "file.mp3"
    file_root.write_bytes(b"x")

    with pytest.raises(LibraryNotFoundError, match="not a directory"):
        list(walk_library(file_root))


def test_single_record_relative_to_parent(library: Path) -> None:
    from organize_music.scanner import single_record

    record = single_record(library / "01 Billie Jean.MP3")

    assert str(record.path) == "01 Billie Jean.MP3"
    assert record.ext == "mp3"


def test_single_record_rejects_non_file(library: Path) -> None:
    from organize_music.scanner import single_record

    with pytest.raises(LibraryNotFoundError, match="not a file"):
        single_record(library / "Carbon Leaf")  # a directory

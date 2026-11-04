"""Tests for file MD5 hashing (side-effect module) and pure duplicate grouping."""

import hashlib
from pathlib import Path

import pytest

from organize_music.dedup import md5_groups, size_collisions
from organize_music.hashing import HashError, md5_file
from organize_music.models import FileRecord


def test_md5_matches_hashlib_across_chunks(tmp_path: Path) -> None:
    data = bytes(range(256)) * 5000  # ~1.2 MB, spans several chunks
    path = tmp_path / "a.mp3"
    path.write_bytes(data)

    assert md5_file(path, chunk_size=4096) == hashlib.md5(data).hexdigest()


def test_md5_of_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.mp3"
    path.write_bytes(b"")

    assert md5_file(path) == hashlib.md5(b"").hexdigest()


def test_md5_missing_file_raises_hash_error(tmp_path: Path) -> None:
    with pytest.raises(HashError, match="FileNotFoundError"):
        md5_file(tmp_path / "nope.mp3")


def rec(name: str, size: int, ext: str = "mp3") -> FileRecord:
    return FileRecord(path=Path(name), size=size, mtime_ns=1, ext=ext)


def test_size_collisions_keeps_only_audio_sharing_a_size() -> None:
    records = [
        rec("a.mp3", 100),
        rec("b.m4a", 100, "m4a"),
        rec("unique.mp3", 200),
        rec("cover.jpg", 100, "jpg"),  # not audio, never a candidate
        rec("empty1.mp3", 0),  # zero-byte files are errors, not duplicates
        rec("empty2.mp3", 0),
    ]

    assert [str(r.path) for r in size_collisions(records)] == ["a.mp3", "b.m4a"]


def test_size_collisions_counts_only_audio_when_matching_sizes() -> None:
    records = [rec("a.mp3", 100), rec("cover.jpg", 100, "jpg")]

    assert size_collisions(records) == []


def test_md5_groups_returns_sorted_groups_of_two_or_more() -> None:
    hashes = {
        Path("z/copy.mp3"): "aaa",
        Path("a/orig.mp3"): "aaa",
        Path("solo.mp3"): "bbb",
        Path("x.mp3"): "ccc",
        Path("y.mp3"): "ccc",
    }

    assert md5_groups(hashes) == [
        ("aaa", [Path("a/orig.mp3"), Path("z/copy.mp3")]),
        ("ccc", [Path("x.mp3"), Path("y.mp3")]),
    ]

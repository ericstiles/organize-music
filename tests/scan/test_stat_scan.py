"""Tests for the stat-only scan into the files table (PLAN §12, issue b8p.28).

``scan_into`` walks a library with ``scanner.walk_library`` and inserts the
audio files whose ``path_key`` is not yet present, kind ``'audio'``, committing
once at the end. It does no updates, no missing detection, no tags, no art.
"""

import sqlite3
from pathlib import Path

from organize_music.db import migrate
from organize_music.db.files_repo import FilesRepo
from organize_music.models import FileRecord
from organize_music.scan import scan_into

NOW = "2026-01-01T00:00:00Z"


def open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrated(tmp_path: Path) -> FilesRepo:
    """A fresh, migrated library.db with a FilesRepo over a writer connection."""
    conn = open_conn(tmp_path / "library.db")
    migrate(conn, tmp_path / "library.db", tmp_path / "backups", NOW)
    return FilesRepo(conn)


def build_library(root: Path) -> None:
    """A temp library with two mp3 files and one jpg."""
    (root / "artist" / "album").mkdir(parents=True)
    (root / "artist" / "album" / "one.mp3").write_bytes(b"\xff\xfbfake-audio")
    (root / "artist" / "album" / "two.mp3").write_bytes(b"\xff\xfbfake-audio")
    (root / "cover.jpg").write_bytes(b"\xff\xd8jpeg")


def test_scan_inserts_audio_files_only(tmp_path: Path) -> None:
    root = tmp_path / "Music"
    build_library(root)
    repo = migrated(tmp_path)

    inserted = scan_into(root, repo, NOW)

    assert inserted == 2
    assert repo.count() == 2
    # The jpg is never inserted; only audio rows exist.
    rows = repo.page(0, 10)
    assert {r.path for r in rows} == {"artist/album/one.mp3", "artist/album/two.mp3"}
    for row in rows:
        assert row.kind == "audio"
        assert row.status == "present"


def test_second_scan_inserts_nothing(tmp_path: Path) -> None:
    root = tmp_path / "Music"
    build_library(root)
    repo = migrated(tmp_path)

    assert scan_into(root, repo, NOW) == 2
    # Every path_key is now present, so a second scan is a no-op.
    assert scan_into(root, repo, NOW) == 0
    assert repo.count() == 2


def test_scan_commits_once_at_end(tmp_path: Path) -> None:
    root = tmp_path / "Music"
    build_library(root)
    conn = open_conn(tmp_path / "library.db")
    migrate(conn, tmp_path / "library.db", tmp_path / "backups", NOW)
    repo = FilesRepo(conn)

    scan_into(root, repo, NOW)
    # A fresh connection sees the rows only because scan committed them.
    reopened = open_conn(tmp_path / "library.db")
    assert FilesRepo(reopened).count() == 2


def test_scan_skips_files_whose_path_key_exists(tmp_path: Path) -> None:
    root = tmp_path / "Music"
    build_library(root)
    repo = migrated(tmp_path)
    # Pre-seed one of the two audio files by its path_key, then commit.
    repo.insert_scanned(
        FileRecord(path=Path("artist/album/one.mp3"), size=1024, mtime_ns=1_700, ext="mp3"),
        "audio",
        NOW,
    )
    repo.commit()

    inserted = scan_into(root, repo, NOW)

    assert inserted == 1  # only two.mp3 is new
    assert repo.count() == 2

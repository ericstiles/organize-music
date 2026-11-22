"""Tests for the crash-test harness (PLAN §11, issue P1-12).

These prove the harness itself: that :class:`FaultyFs` raises a crash at the
right moment, that :class:`SimulatedCrash` escapes ``except Exception``, that
:func:`count_calls` and :func:`content_hashes` count and hash as documented,
and that :func:`assert_consistent` passes on a clean tree and fails when a file
is missing or a present row's size lies.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from support.faulty_fs import FaultyFs, SimulatedCrash, count_calls
from support.invariants import assert_consistent, content_hashes


class Recorder:
    """A minimal in-memory :class:`FsOps` that records which method was called."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def rename_noreplace(self, src: Path, dst: Path) -> None:
        self.calls.append("rename_noreplace")

    def fsync_file(self, path: Path) -> None:
        self.calls.append("fsync_file")

    def fsync_dir(self, path: Path) -> None:
        self.calls.append("fsync_dir")

    def mkdir_one(self, path: Path) -> None:
        self.calls.append("mkdir_one")

    def rmdir_if_empty(self, path: Path) -> bool:
        self.calls.append("rmdir_if_empty")
        return False

    def copy_new(self, src: Path, dst: Path) -> None:
        self.calls.append("copy_new")

    def discard_temp(self, work_dir: Path, path: Path) -> None:
        self.calls.append("discard_temp")

    def entry_exists(self, parent: Path, name: str) -> bool:
        self.calls.append("entry_exists")
        return False

    def same_device(self, *paths: Path) -> bool:
        self.calls.append("same_device")
        return True


def test_faulty_fs_crashes_before_the_nth_call_and_inner_is_untouched() -> None:
    inner = Recorder()
    fault = FaultyFs(inner, crash_at=3, when="before")
    try:
        fault.rename_noreplace(Path("a"), Path("b"))
        fault.fsync_file(Path("a"))
        fault.fsync_dir(Path("a"))  # call number 3, "before": crash first
    except SimulatedCrash:
        pass
    else:
        raise AssertionError("expected SimulatedCrash on the third call")
    # "before" means the inner is never reached on the crashing call.
    assert inner.calls == ["rename_noreplace", "fsync_file"]
    assert fault.calls == 3  # every method call is counted, including the crash


def test_faulty_fs_crashes_after_the_nth_call_and_inner_is_reached() -> None:
    inner = Recorder()
    fault = FaultyFs(inner, crash_at=2, when="after")
    try:
        fault.rename_noreplace(Path("a"), Path("b"))
        fault.fsync_file(Path("a"))  # call number 2: inner runs, then crash
    except SimulatedCrash:
        pass
    else:
        raise AssertionError("expected SimulatedCrash after the second call")
    # "after" means the inner IS reached before the crash on that call.
    assert inner.calls == ["rename_noreplace", "fsync_file"]
    assert fault.calls == 2


def test_faulty_fs_passes_through_until_the_crash_point() -> None:
    inner = Recorder()
    fault = FaultyFs(inner, crash_at=99, when="before")
    fault.rename_noreplace(Path("a"), Path("b"))
    fault.fsync_file(Path("a"))
    assert inner.calls == ["rename_noreplace", "fsync_file"]
    assert fault.calls == 2


def test_simulated_crash_is_not_caught_by_except_exception() -> None:
    inner = Recorder()
    fault = FaultyFs(inner, crash_at=1, when="before")

    # If SimulatedCrash were an Exception, the inner `except Exception` would
    # swallow it and this assertion would fire; instead the crash escapes it.
    def inner_run() -> None:
        try:
            fault.rename_noreplace(Path("a"), Path("b"))
        except Exception:
            raise AssertionError("SimulatedCrash was swallowed by except Exception") from None

    try:
        inner_run()
    except SimulatedCrash:
        pass  # escaped the inner except Exception, caught by its own type
    else:
        raise AssertionError("expected SimulatedCrash to propagate")


def test_count_calls_runs_once_and_returns_total() -> None:
    inner = Recorder()

    def run(fs: FaultyFs) -> object:
        fs.rename_noreplace(Path("a"), Path("b"))
        fs.fsync_file(Path("a"))
        return None

    assert count_calls(run, inner) == 2
    assert inner.calls == ["rename_noreplace", "fsync_file"]


def _open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _make_file(root: Path, rel: str, payload: bytes) -> None:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    # A deterministic, reproducible mtime so the assertion does not race the
    # filesystem clock.
    ns = 1_700_000_000_000_000_000
    os.utime(target, ns=2 * (ns,))


def _insert_present(conn: sqlite3.Connection, rel: str, size: int, mtime_ns: int) -> None:
    conn.execute(
        "INSERT INTO files "
        "(path, path_key, last_path, status, kind, size, mtime_ns, ext, "
        "artist, artist_src, album_artist, album_artist_src, album, album_src, "
        "title, title_src, track_number, track_number_src, disc_number, "
        "disc_number_src, year, year_src, genre, genre_src, row_version, "
        "first_seen_at, updated_at) "
        "VALUES (?, ?, ?, 'present', 'audio', ?, ?, ?, "
        "'a', 'tag', 'a', 'tag', 'a', 'tag', 't', 'tag', '1', 'tag', '1', 'tag', "
        "'2001', 'tag', 'Rock', 'tag', 1, '2026-01-01T00:00:00Z', "
        "'2026-01-01T00:00:00Z')",
        (rel, rel.casefold(), rel, size, mtime_ns, "mp3"),
    )
    conn.commit()


def _build_db(tmp_path: Path) -> sqlite3.Connection:
    """A freshly migrated library.db plus a present row and its real file."""
    from organize_music.db.migrations import migrate

    root = tmp_path / "lib"
    root.mkdir()
    _make_file(root, "a/b/c.mp3", b"hello")
    mtime_ns = 1_700_000_000_000_000_000

    path = tmp_path / "library.db"
    conn = _open_conn(path)
    migrate(conn, path, tmp_path / "backups", "2026-01-01T00:00:00Z")
    _insert_present(conn, "a/b/c.mp3", size=len(b"hello"), mtime_ns=mtime_ns)
    return conn


def test_assert_consistent_passes_on_a_clean_tree(tmp_path: Path) -> None:
    conn = _build_db(tmp_path)
    try:
        root = tmp_path / "lib"
        original = content_hashes(root)
        # A pristine tree must pass with no extra dirs and a clean op log.
        assert_consistent(root, conn, extra_dirs=(), original=original)
    finally:
        conn.close()


def test_assert_consistent_fails_when_a_file_is_removed(tmp_path: Path) -> None:
    conn = _build_db(tmp_path)
    try:
        root = tmp_path / "lib"
        original = content_hashes(root)
        (root / "a/b/c.mp3").unlink()
        try:
            assert_consistent(root, conn, extra_dirs=(), original=original)
        except AssertionError:
            pass
        else:
            raise AssertionError("assert_consistent must fail when a file is removed")
    finally:
        conn.close()


def test_assert_consistent_fails_when_a_present_row_size_is_wrong(tmp_path: Path) -> None:
    conn = _build_db(tmp_path)
    try:
        root = tmp_path / "lib"
        original = content_hashes(root)
        # The row claims a size the file on disk does not have.
        conn.execute(
            "UPDATE files SET size = 99999 WHERE path = ?",
            ("a/b/c.mp3",),
        )
        conn.commit()
        try:
            assert_consistent(root, conn, extra_dirs=(), original=original)
        except AssertionError:
            pass
        else:
            raise AssertionError("assert_consistent must fail on a wrong row size")
    finally:
        conn.close()


def test_assert_consistent_fails_on_an_active_operation(tmp_path: Path) -> None:
    conn = _build_db(tmp_path)
    try:
        root = tmp_path / "lib"
        original = content_hashes(root)
        # A batch and an in-flight operation: state 'staged' is ACTIVE.
        conn.execute(
            "INSERT INTO batches "
            "(kind, state, description, request_json, created_at) "
            "VALUES ('rename', 'running', 'b', '{}', '2026-01-01T00:00:00Z')"
        )
        batch_id = int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])
        conn.execute(
            "INSERT INTO operations "
            "(batch_id, file_id, unit_seq, step_seq, kind, state, expect_path, "
            "expect_size, expect_mtime_ns, expect_row_version, params_json, "
            "created_at, updated_at) "
            "VALUES (?, ?, 0, 0, 'move', 'staged', 'a/b/c.mp3', 5, 1, 1, '{}', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')",
            (batch_id, 1),
        )
        conn.commit()
        try:
            assert_consistent(root, conn, extra_dirs=(), original=original)
        except AssertionError:
            pass
        else:
            raise AssertionError("assert_consistent must fail on an active operation")
    finally:
        conn.close()

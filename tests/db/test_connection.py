"""Tests for the single-writer DB connections and the exclusive writer lock.

The writer owns library.db's only write connection (WAL, synchronous=FULL,
foreign_keys on); readers get a query_only connection so HTTP handlers can read
concurrently. A second WriterLock on the same path must fail with WriterBusy,
and the lock must be released when the with-block exits.
"""

import fcntl
import os
import sqlite3

import pytest

from organize_music.db import WriterBusy, WriterLock, open_reader, open_writer


def test_writer_pragmas(tmp_path):
    path = tmp_path / "library.db"
    conn = open_writer(path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert conn.execute("PRAGMA synchronous").fetchone()[0] == 2
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 0
    finally:
        conn.close()


def test_reader_pragmas(tmp_path):
    path = tmp_path / "library.db"
    open_writer(path).close()
    conn = open_reader(path)
    try:
        assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    finally:
        conn.close()


def test_writer_has_row_factory(tmp_path):
    conn = open_writer(tmp_path / "library.db")
    try:
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_reader_has_row_factory(tmp_path):
    path = tmp_path / "library.db"
    open_writer(path).close()
    conn = open_reader(path)
    try:
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()


def test_write_through_reader_raises(tmp_path):
    path = tmp_path / "library.db"
    open_writer(path).close()
    conn = open_reader(path)
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute("CREATE TABLE t (x INTEGER)")
    finally:
        conn.close()


def test_reader_on_missing_path_does_not_create_it(tmp_path):
    # A read-only connection must never create the file (organize_music-8gz):
    # a missing library.db must raise and leave no file behind.
    path = tmp_path / "library.db"
    with pytest.raises(sqlite3.OperationalError):
        open_reader(path)
    assert not path.exists()


def test_second_writer_lock_is_busy(tmp_path):
    lock_path = tmp_path / "writer.lock"
    first = WriterLock(lock_path)
    with first:
        with pytest.raises(WriterBusy) as exc:
            second = WriterLock(lock_path)
            second.__enter__()
    assert str(exc.value) == "server is running"


def test_lock_released_after_block(tmp_path):
    lock_path = tmp_path / "writer.lock"
    with WriterLock(lock_path):
        pass
    # A fresh lock on the same path succeeds once the first is released.
    with WriterLock(lock_path):
        pass


def test_writer_lock_is_a_context_manager(tmp_path):
    lock = WriterLock(tmp_path / "writer.lock")
    assert lock.__enter__() is lock


def test_enter_closes_fd_on_unexpected_error(tmp_path, monkeypatch):
    # If fcntl.flock raises an error other than BlockingIOError, the fd opened
    # by os.open must still be closed (no descriptor leak).
    lock_path = tmp_path / "writer.lock"
    opened_fds: list[int] = []

    real_open = os.open

    def recording_open(*args, **kwargs):
        fd = real_open(*args, **kwargs)
        opened_fds.append(fd)
        return fd

    def raise_oserror(*args, **kwargs):
        raise OSError("simulated flock failure")

    monkeypatch.setattr(os, "open", recording_open)
    monkeypatch.setattr(fcntl, "flock", raise_oserror)

    lock = WriterLock(lock_path)
    with pytest.raises(OSError):
        lock.__enter__()

    # The fd os.open handed us must be closed; fstat on it now raises.
    leaked_fd = opened_fds[-1]
    with pytest.raises(OSError):
        os.fstat(leaked_fd)

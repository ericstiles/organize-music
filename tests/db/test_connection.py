"""Tests for the single-writer DB connections and the exclusive writer lock.

The writer owns library.db's only write connection (WAL, synchronous=FULL,
foreign_keys on); readers get a query_only connection so HTTP handlers can read
concurrently. A second WriterLock on the same path must fail with WriterBusy,
and the lock must be released when the with-block exits.
"""

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

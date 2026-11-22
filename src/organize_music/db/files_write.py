"""Compare-and-set write over the ``files`` table of library.db (PLAN §6.2).

The committed move updates its row in one statement: ``path``, ``path_key``,
``last_path``, ``size``, ``mtime_ns`` and ``updated_at`` are written and
``row_version`` is bumped by one, but only when the row's ``row_version`` still
matches the caller's expectation and the row is still ``'present'``. That
``WHERE file_id = ? AND row_version = ? AND status = 'present'`` guard is the
compare-and-set: nobody may have changed the row since the precondition was read.

A guard mismatch (stale version, or a non-``'present'`` row) leaves the row
untouched and raises :class:`StaleRow`; a ``path_key`` that collides with
another row's (the exFAT case-insensitive unique index) raises
:class:`PathTaken`. ``update_path`` commits nothing: the caller wraps it with the
op state change in one transaction.
"""

from __future__ import annotations

import sqlite3

from organize_music.paths import path_key


class StaleRow(Exception):
    """The row's ``row_version`` no longer matches, or it is not ``'present'``.

    The compare-and-set guard matched nothing, so the row is left unchanged.
    """


class PathTaken(Exception):
    """The new ``path_key`` already belongs to another row.

    The exFAT collision index rejects the update, so the row is left unchanged.
    """


def update_path(
    conn: sqlite3.Connection,
    file_id: int,
    expect_row_version: int,
    new_path: str,
    size: int,
    mtime_ns: int,
    now: str,
) -> None:
    """Move ``file_id``'s row to ``new_path``, guarded by the expected version.

    Writes ``path``, ``path_key`` (``paths.path_key`` of ``new_path``),
    ``last_path``, ``size``, ``mtime_ns`` and ``updated_at``, and bumps
    ``row_version`` by one, but only when the current ``row_version`` equals
    ``expect_row_version`` and ``status`` is ``'present'``. Raises
    :class:`StaleRow` when nothing matched and :class:`PathTaken` on a
    ``path_key`` collision. Does not commit.
    """
    key = path_key(new_path)
    try:
        cur = conn.execute(
            "UPDATE files SET path = ?, path_key = ?, last_path = ?, size = ?, "
            "mtime_ns = ?, row_version = row_version + 1, updated_at = ? "
            "WHERE file_id = ? AND row_version = ? AND status = 'present'",
            (new_path, key, new_path, size, mtime_ns, now, file_id, expect_row_version),
        )
    except sqlite3.IntegrityError as exc:
        raise PathTaken(f"path_key for {new_path!r} is already taken") from exc
    if cur.rowcount == 0:
        raise StaleRow(f"file {file_id} not updatable at row_version {expect_row_version}")

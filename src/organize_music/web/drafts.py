"""The web process's scratch draft database (PLAN §6.4, issue b8p.30).

A preview stores its planned units as a draft batch in ``state_dir/drafts.db``,
a scratch database owned by the web process, and never into ``library.db``:
drafts and selection snapshots never touch ``library.db``, which keeps exactly
one writer (plan revised 2026-11-17). The two tables below mirror ``batches``
and ``operations`` from migration ``0001_initial.sql`` -- keep them in sync if
that migration ever changes. The scratch database carries no ``files`` table
and is opened with foreign keys off: a draft op is a snapshot of a library.db
row, and the real reference checks happen when a confirmed draft is copied
into ``library.db``.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from organize_music.ops.move import plan_move_params

# The scratch database file, beside library.db in state_dir.
NAME = "drafts.db"

# Must stay in sync with the batches and operations tables of
# db/migrations/0001_initial.sql (the schema of PLAN §5).
_SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (
  batch_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  kind         TEXT NOT NULL CHECK (kind IN ('rename','edit','undo','quarantine')),
  state        TEXT NOT NULL CHECK (state IN ('draft','confirmed','running','completed',
                 'completed_with_errors','stopped','cancelled','discarded')),
  description  TEXT NOT NULL,
  request_json TEXT NOT NULL,     -- the validated request that produced the preview
  undo_of      INTEGER REFERENCES batches(batch_id),
  total INTEGER NOT NULL DEFAULT 0, succeeded INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, confirmed_at TEXT, finished_at TEXT
);

CREATE TABLE IF NOT EXISTS operations (
  op_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id      INTEGER NOT NULL REFERENCES batches(batch_id),
  file_id       INTEGER NOT NULL REFERENCES files(file_id),
  unit_seq      INTEGER NOT NULL,
  step_seq      INTEGER NOT NULL,
  kind          TEXT NOT NULL CHECK (kind IN ('move','retag')),
  state         TEXT NOT NULL CHECK (state IN ('planned','intent','staged','parked','applied',
                  'committed','failed','skipped','needs_attention')),
  expect_path TEXT NOT NULL, expect_size INTEGER NOT NULL,
  expect_mtime_ns INTEGER NOT NULL, expect_row_version INTEGER NOT NULL,
  params_json   TEXT NOT NULL,
  result_json   TEXT,
  error_code    TEXT, error_detail TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (batch_id, unit_seq, step_seq)
);
"""


@dataclass(frozen=True)
class Draft:
    """A draft batch with its single planned operation (the rename tracer)."""

    batch_id: int
    kind: str
    description: str
    request_json: str
    op_id: int
    file_id: int
    op_kind: str
    op_state: str
    expect_path: str
    expect_size: int
    expect_mtime_ns: int
    expect_row_version: int
    params_json: str

    def op_values(self, now: str) -> tuple[int, str, str, int, int, int, str, str, str]:
        """The op's insert values for library.db (see rename_confirm._copy_batch)."""
        return (
            self.file_id,
            self.op_kind,
            self.expect_path,
            self.expect_size,
            self.expect_mtime_ns,
            self.expect_row_version,
            self.params_json,
            now,
            now,
        )


def open_drafts(state_dir: Path) -> sqlite3.Connection:
    """Open the scratch database, creating and initialising it when missing.

    No ``foreign_keys=ON``: draft ops reference library.db rows, which this
    scratch database does not hold.
    """
    path = state_dir / NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA)
    return conn


def save_draft(
    conn: sqlite3.Connection,
    *,
    new_name: str,
    file_id: int,
    src_rel: str,
    dst_rel: str,
    size: int,
    mtime_ns: int,
    row_version: int,
    now: str,
) -> int:
    """Store one draft batch with a planned move op; return the batch id.

    Both rows are written in one transaction. The op's ``expect_*`` tuple is
    the precondition captured from the ``files`` row at preview time; the move
    re-checks it (and re-stats the disk) before its first disk action.
    """
    conn.execute("BEGIN")
    try:
        cur = conn.execute(
            "INSERT INTO batches (kind, state, description, request_json, created_at) "
            "VALUES ('rename', 'draft', ?, ?, ?)",
            (
                f"rename {src_rel} to {new_name}",
                json.dumps({"file_id": file_id, "new_name": new_name}),
                now,
            ),
        )
        batch_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO operations (batch_id, file_id, unit_seq, step_seq, kind, state, "
            "expect_path, expect_size, expect_mtime_ns, expect_row_version, params_json, "
            "created_at, updated_at) "
            "VALUES (?, ?, 0, 0, 'move', 'planned', ?, ?, ?, ?, ?, ?, ?)",
            (
                batch_id,
                file_id,
                src_rel,
                size,
                mtime_ns,
                row_version,
                json.dumps(plan_move_params(src_rel, dst_rel, str(batch_id))),
                now,
                now,
            ),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return batch_id


def delete_draft(conn: sqlite3.Connection, batch_id: int) -> None:
    """Delete a consumed draft batch with its operations (no-op when absent)."""
    conn.execute("DELETE FROM operations WHERE batch_id = ?", (batch_id,))
    conn.execute("DELETE FROM batches WHERE batch_id = ?", (batch_id,))
    conn.commit()


def load_draft(conn: sqlite3.Connection, batch_id: int) -> Draft | None:
    """Return the draft batch and its operation, or None when absent."""
    batch = conn.execute("SELECT * FROM batches WHERE batch_id = ?", (batch_id,)).fetchone()
    if batch is None:
        return None
    op = conn.execute(
        "SELECT * FROM operations WHERE batch_id = ? ORDER BY op_id", (batch_id,)
    ).fetchone()
    if op is None:  # a stored draft always has at least one operation
        raise ValueError(f"draft batch {batch_id} has no operations")
    return Draft(
        batch_id=batch["batch_id"],
        kind=batch["kind"],
        description=batch["description"],
        request_json=batch["request_json"],
        op_id=op["op_id"],
        file_id=op["file_id"],
        op_kind=op["kind"],
        op_state=op["state"],
        expect_path=op["expect_path"],
        expect_size=op["expect_size"],
        expect_mtime_ns=op["expect_mtime_ns"],
        expect_row_version=op["expect_row_version"],
        params_json=op["params_json"],
    )

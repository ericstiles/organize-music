"""The crash-safe operation log over the ``operations`` table (PLAN §6.2/§6.3).

Each :meth:`OplogRepo.transition` is one durable transaction: it checks the
transition is allowed (else raises :class:`IllegalTransition` and writes
nothing), runs an optional ``extra`` that writes the effect on the ``files``
table (e.g. ``files_write.update_path``) without committing, updates the
operation row, commits, and only then appends a record to the JSONL mirror. If
``extra`` raises, the transaction rolls back and the mirror is not touched, so a
crash mid-move leaves the log and the files in the last committed, consistent
state.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from organize_music.ops._rows import SELECT as _SELECT
from organize_music.ops._rows import record
from organize_music.ops.states import ACTIVE, is_allowed


class IllegalTransition(Exception):
    """The transition ``(kind, from_state) -> to_state`` is not in ``ALLOWED``.

    Nothing is written: the operation row is left exactly as it was.
    """


@dataclass(frozen=True)
class Operation:
    """One row of the ``operations`` table, as the move op and web page read it."""

    op_id: int
    batch_id: int
    file_id: int
    unit_seq: int
    step_seq: int
    kind: str
    state: str
    expect_path: str
    expect_size: int
    expect_mtime_ns: int
    expect_row_version: int
    params: Mapping[str, object]
    error_code: str | None


class OplogRepo:
    """Durable, transition-checked access to the ``operations`` table.

    ``mirror`` receives one mapping per successful transition (the JSONL mirror
    is P1-11; tests inject ``list.append``); ``clock`` supplies the UTC
    timestamp written into the row and the record.
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        mirror: Callable[[Mapping[str, object]], None],
        clock: Callable[[], str],
    ) -> None:
        self._conn = conn
        self._mirror = mirror
        self._clock = clock

    def create_batch(self, kind: str, description: str, request_json: str) -> int:
        """Insert a new batch in the ``'draft'`` state and return its id."""
        now = self._clock()
        cur = self._conn.execute(
            "INSERT INTO batches (kind, state, description, request_json, created_at) "
            "VALUES (?, 'draft', ?, ?, ?)",
            (kind, description, request_json, now),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def add_op(
        self,
        batch_id: int,
        file_id: int,
        unit_seq: int,
        step_seq: int,
        kind: str,
        expect: tuple[str, int, int, int],
        params: Mapping[str, object],
    ) -> int:
        """Add an operation in the ``'planned'`` state and return its id.

        ``expect`` is ``(expect_path, expect_size, expect_mtime_ns,
        expect_row_version)``: the precondition the move later compares against.
        """
        now = self._clock()
        cur = self._conn.execute(
            "INSERT INTO operations "
            "(batch_id, file_id, unit_seq, step_seq, kind, state, expect_path, "
            "expect_size, expect_mtime_ns, expect_row_version, params_json, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'planned', ?, ?, ?, ?, ?, ?, ?)",
            (
                batch_id,
                file_id,
                unit_seq,
                step_seq,
                kind,
                expect[0],
                expect[1],
                expect[2],
                expect[3],
                json.dumps(params),
                now,
                now,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def get(self, op_id: int) -> Operation:
        """Return the operation with ``op_id`` (raises if it does not exist)."""
        row = self._conn.execute(_SELECT + " WHERE op_id = ?", (op_id,)).fetchone()
        if row is None:
            raise KeyError(op_id)
        return _to_op(row)

    def transition(
        self,
        op_id: int,
        to: str,
        params: Mapping[str, object] | None = None,
        error: tuple[str, str] | None = None,
        extra: Callable[[sqlite3.Connection], None] | None = None,
    ) -> Operation:
        """Move the op to ``to`` in one transaction; mirror the record.

        An illegal transition raises :class:`IllegalTransition` and writes
        nothing. ``extra`` runs inside the transaction (committing nothing)
        before the row update; if it raises, the transaction rolls back and the
        mirror is not called, leaving the op and the files in their last
        committed state.
        """
        op = self.get(op_id)
        if not is_allowed(op.kind, op.state, to):
            raise IllegalTransition(
                f"{op.kind} {op.state!r} -> {to!r} is not an allowed transition"
            )
        now = self._clock()
        new_params = params if params is not None else op.params
        error_code, error_detail = error if error is not None else (op.error_code, None)
        try:
            if extra is not None:
                extra(self._conn)
            self._conn.execute(
                "UPDATE operations SET state = ?, params_json = ?, error_code = ?, "
                "error_detail = ?, updated_at = ? WHERE op_id = ?",
                (to, json.dumps(new_params), error_code, error_detail, now, op_id),
            )
            self._conn.commit()
        except BaseException:
            self._conn.rollback()
            raise
        self._mirror(record(op, to, new_params, error_code, now))
        return self.get(op_id)

    def active_ops(self) -> list[Operation]:
        """Every operation in an :data:`ACTIVE` state, ordered by ``op_id``."""
        marks = ", ".join("?" for _ in ACTIVE)
        rows = self._conn.execute(
            f"{_SELECT} WHERE state IN ({marks}) ORDER BY op_id", tuple(ACTIVE)
        ).fetchall()
        return [_to_op(r) for r in rows]


def _to_op(row: sqlite3.Row) -> Operation:
    """Map an ``operations`` row to an :class:`Operation` (``params_json`` parsed)."""
    return Operation(
        op_id=row["op_id"],
        batch_id=row["batch_id"],
        file_id=row["file_id"],
        unit_seq=row["unit_seq"],
        step_seq=row["step_seq"],
        kind=row["kind"],
        state=row["state"],
        expect_path=row["expect_path"],
        expect_size=row["expect_size"],
        expect_mtime_ns=row["expect_mtime_ns"],
        expect_row_version=row["expect_row_version"],
        params=json.loads(row["params_json"]),
        error_code=row["error_code"],
    )

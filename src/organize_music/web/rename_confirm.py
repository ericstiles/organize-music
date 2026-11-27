"""Confirm side of rename-one (b8p.30, PLAN §6.4/§9.4): re-check the draft's
``row_version`` precondition, consume it, copy it into library.db, run
``run_move`` and settle the batch.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import UTC, datetime

from fastapi import Request
from fastapi.responses import Response
from starlette.datastructures import State

from organize_music.db.connection import WriterBusy, WriterLock, open_writer
from organize_music.fsops.protocol import RealFs
from organize_music.ops.context import OpContext
from organize_music.ops.mirror import make_mirror
from organize_music.ops.move import run_move
from organize_music.ops.oplog_repo import Operation, OplogRepo
from organize_music.web import drafts

_LOG = logging.getLogger(__name__)

_DISABLED = ("MUTATIONS_DISABLED", "mutations are disabled (config mutations_enabled: false)")
_NOT_CONFIGURED = ("LIBRARY_NOT_CONFIGURED", "set the config 'library' path")
_NOT_INIT = ("NOT_INITIALISED", "run the scan first")
_WRITER_BUSY = ("WRITER_BUSY", "another writer holds the lock")
_STALE = ("PREVIEW_STALE", "the file changed since the preview; re-preview")


def _utcnow() -> str:
    """A UTC timestamp for the rows and the operation mirror."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _schema_ok(conn: sqlite3.Connection) -> bool:
    """True when the database has the migrated ``files`` table."""
    try:
        conn.execute("SELECT 1 FROM files LIMIT 1").fetchone()
        return True
    except sqlite3.Error:
        return False


def _dst_of(params_json: str) -> str | None:
    try:
        return json.loads(params_json).get("dst")
    except (json.JSONDecodeError, AttributeError):
        return None


def confirm(request: Request, batch_id: int) -> Response:
    """Confirm a draft: guards, writer lock, re-check, run, render (PLAN §9.4)."""
    state = request.app.state
    if not state.mutations_enabled:
        return _render(request, batch_id, None, None, None, _DISABLED, 403)
    if state.library_root is None:
        return _render(request, batch_id, None, None, None, _NOT_CONFIGURED, 503)
    db_path = state.db_path
    if not db_path.is_file():
        return _render(request, batch_id, None, None, None, _NOT_INIT, 503)
    if state.writer_lock is not None:
        # The process owns the writer lock (serve holds it for the server's
        # lifetime, PLAN §6.4 "One writer"); a second in-process acquisition
        # is always denied, so write directly without re-acquiring.
        conn = open_writer(db_path)
    else:
        try:
            with WriterLock(state.state_dir / "writer.lock"):
                conn = open_writer(db_path)
        except WriterBusy:
            return _render(request, batch_id, None, None, None, _WRITER_BUSY, 503)
    try:
        return _confirm_in_conn(request, state, conn, batch_id)
    finally:
        conn.close()


def _confirm_in_conn(
    request: Request, state: State, conn: sqlite3.Connection, batch_id: int
) -> Response:
    """Re-check the draft, copy it into library.db, run and settle the op.

    The draft is consumed before the copy: a crash in between loses the draft
    but changes nothing; a crash after the copy leaves the op for recovery.
    """
    if not _schema_ok(conn):
        return _render(request, batch_id, None, None, None, _NOT_INIT, 503)
    dconn = drafts.open_drafts(state.state_dir)
    try:
        draft = drafts.load_draft(dconn, batch_id)
        if draft is None:
            err = ("NOT_FOUND", f"no draft batch {batch_id}")
            return _render(request, batch_id, None, None, None, err, 404)
        cur = conn.execute(
            "SELECT row_version FROM files WHERE file_id = ?", (draft.file_id,)
        ).fetchone()
        if cur is None or int(cur["row_version"]) != draft.expect_row_version:
            return _render(request, batch_id, draft, None, None, _STALE, 409)
        drafts.delete_draft(dconn, batch_id)
    finally:
        dconn.close()
    lib_batch_id, op_id = _copy_batch(conn, draft)
    oplog = OplogRepo(conn, mirror=make_mirror(state.work_dir, _utcnow), clock=_utcnow)
    ctx = OpContext(
        root=state.library_root,
        work_dir=state.work_dir,
        purge_dir=state.purge_dir,
        fs=RealFs(),
        oplog=oplog,
        conn=conn,
        clock=_utcnow,
    )
    try:
        final = run_move(oplog.get(op_id), ctx)
    except Exception as exc:  # noqa: BLE001 - the op stays where it stopped
        # run_move stops only in terminal states; startup recovery re-runs it.
        _LOG.warning("confirm %s: run_move raised %s", batch_id, exc)
        msg = f"stopped with {type(exc).__name__}; it will be recovered at the next startup"
        return _render(request, batch_id, draft, None, msg, None, 200)
    _settle_batch(conn, lib_batch_id, final)
    return _render(request, batch_id, draft, final, None, None, 200)


def _copy_batch(conn: sqlite3.Connection, draft: drafts.Draft) -> tuple[int, int]:
    """Copy the draft batch and its op into library.db in one transaction."""
    now = _utcnow()
    conn.execute("BEGIN")
    try:
        cur = conn.execute(
            "INSERT INTO batches (kind, state, description, request_json, created_at, "
            "confirmed_at) VALUES (?, 'running', ?, ?, ?, ?)",
            (draft.kind, draft.description, draft.request_json, now, now),
        )
        batch_id = int(cur.lastrowid)
        op_cur = conn.execute(
            "INSERT INTO operations (batch_id, file_id, unit_seq, step_seq, kind, state, "
            "expect_path, expect_size, expect_mtime_ns, expect_row_version, params_json, "
            "created_at, updated_at) VALUES (?, ?, 0, 0, ?, 'planned', ?, ?, ?, ?, ?, ?, ?)",
            (batch_id, *draft.op_values(now)),
        )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    return batch_id, int(op_cur.lastrowid)


def _settle_batch(conn: sqlite3.Connection, batch_id: int, final: Operation) -> None:
    """Count the one op's outcome into the batch and end it."""
    if final.state == "committed":
        state, succeeded, failed = "completed", 1, 0
    else:
        state, succeeded, failed = "completed_with_errors", 0, 1
    conn.execute(
        "UPDATE batches SET state = ?, total = 1, succeeded = ?, failed = ?, "
        "skipped = 0, finished_at = ? WHERE batch_id = ?",
        (state, succeeded, failed, _utcnow(), batch_id),
    )
    conn.commit()


def _ctx(
    batch_id: int,
    draft: drafts.Draft | None,
    final: Operation | None,
    halted: str | None,
    error: dict[str, str] | None,
) -> dict[str, object]:
    """The batch_result.html template context."""
    return {
        "batch_id": batch_id,
        "file_id": draft.file_id if draft else None,
        "old_path": draft.expect_path if draft else None,
        "new_path": _dst_of(draft.params_json) if draft else None,
        "state": final.state if final else None,
        "error_code": final.error_code if final else None,
        "halted": halted,
        "error": error,
    }


def _render(
    request: Request,
    batch_id: int,
    draft: drafts.Draft | None,
    final: Operation | None,
    halted: str | None,
    error: tuple[str, str] | None,
    status_code: int,
) -> Response:
    """Render batch_result.html for a confirm error or outcome."""
    template = request.app.state.templates
    err = {"code": error[0], "message": error[1]} if error else None
    context = _ctx(batch_id, draft, final, halted, err)
    return template.TemplateResponse(request, "batch_result.html", context, status_code=status_code)

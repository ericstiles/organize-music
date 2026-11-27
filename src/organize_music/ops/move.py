"""The move operation: the tracer's one mutation (PLAN §6.2, issue b8p.22).

``run_move`` drives one operation through the §6.2 table
``planned -> intent -> [staged] -> applied -> committed`` and stops at a
terminal state. It renames exactly one file, journaled in the operation log,
never replacing anything: every disk action is a no-replace rename, every step
is durable before the next, and a crash leaves the content at exactly one of
``{src, via, dst}`` (recovery, P1-14, decides which). A precondition mismatch
or collision fails the op without moving the file.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from organize_music.db import files_write
from organize_music.ops.context import OpContext
from organize_music.ops.oplog_repo import Operation
from organize_music.ops.states import TERMINAL
from organize_music.paths import is_case_only, path_key, resolve_target


def plan_move_params(src: str, dst: str, op_id_hint: str) -> dict[str, object]:
    """The ``params_json`` a move op starts with (PLAN §6.2).

    ``via`` is the intermediate name for a case-only rename (``<parent>/
    .om-<op_id>.tmp`` in the source folder); ``created_dirs`` is filled in by
    :func:`run_move`. ``dst_root`` is ``'library'`` (quarantine is later).
    """
    via = None
    if is_case_only(src, dst):
        folder = src.rsplit("/", 1)[0] if "/" in src else ""
        via = f"{folder}/.om-{op_id_hint}.tmp" if folder else f".om-{op_id_hint}.tmp"
    return {"src": src, "dst": dst, "via": via, "created_dirs": [], "dst_root": "library"}


def run_move(op: Operation, ctx: OpContext) -> Operation:
    """Drive ``op`` to a terminal state, returning the final operation row."""
    op = ctx.oplog.get(op.op_id)
    while op.state not in TERMINAL:
        op = _step(op, ctx)
        # Fault hook (b8p.34): sleep after reaching a state named by OM_FAULT_SLEEP_AFTER.
        if os.environ.get("OM_FAULT_SLEEP_AFTER") == op.state:
            time.sleep(30.0)
    if op.state == "committed":
        _cleanup_empty_dirs(ctx, op)
    return ctx.oplog.get(op.op_id)


def _step(op: Operation, ctx: OpContext) -> Operation:
    """One durable step of the §6.2 table, keyed by the op's current state."""
    handler = {
        "planned": _planned,
        "intent": _intent,
        "staged": _staged,
        "applied": _applied,
    }[op.state]
    return handler(op, ctx)


def _planned(op: Operation, ctx: OpContext) -> Operation:
    """Recheck the precondition, validate the destination, then go to intent."""
    src_path = ctx.root / op.expect_path
    dst_rel: str = op.params["dst"]

    # Precondition: the source still matches what the op captured.
    try:
        st = os.stat(src_path)
    except FileNotFoundError:
        return _fail(ctx, op, "PRECONDITION_FAILED", mark_changed=True)
    if st.st_size != op.expect_size or st.st_mtime_ns != op.expect_mtime_ns:
        return _fail(ctx, op, "PRECONDITION_FAILED", mark_changed=True)
    row = ctx.conn.execute(
        "SELECT status, row_version FROM files WHERE file_id = ?", (op.file_id,)
    ).fetchone()
    if row is None or row[0] != "present" or int(row[1]) != op.expect_row_version:
        return _fail(ctx, op, "PRECONDITION_FAILED", mark_changed=True)

    # Destination: refuse symlinks/escapes, then confirm it is free. A
    # case-only rename shares the source's own path_key, so the collision
    # check must look past the row being moved.
    dst_path = resolve_target(ctx.root, dst_rel)
    if _dst_taken(ctx, op, dst_rel):
        return _fail(ctx, op, "COLLISION", mark_changed=False)
    if ctx.fs.entry_exists(dst_path.parent, dst_path.name):
        return _fail(ctx, op, "COLLISION", mark_changed=False)
    if not ctx.fs.same_device(src_path, _existing_ancestor(ctx.root, dst_path)):
        return _fail(ctx, op, "CROSS_DEVICE", mark_changed=False)

    params = {**op.params, "created_dirs": _missing_parents(ctx.root, dst_path)}
    return ctx.oplog.transition(op.op_id, "intent", params=params)


def _intent(op: Operation, ctx: OpContext) -> Operation:
    """Create the missing folders, then the first (no-replace) rename."""
    created = op.params.get("created_dirs") or []
    via = op.params.get("via")
    src_path = ctx.root / op.expect_path
    dst_path = ctx.root / op.params["dst"]
    for d in created:
        ctx.fs.mkdir_one(Path(d))
    if via is not None:
        via_path = ctx.root / via
        ctx.fs.rename_noreplace(src_path, via_path)
        ctx.fs.fsync_dir(src_path.parent)
        ctx.fs.fsync_dir(via_path.parent)
        return ctx.oplog.transition(op.op_id, "staged")
    ctx.fs.rename_noreplace(src_path, dst_path)
    ctx.fs.fsync_dir(src_path.parent)
    ctx.fs.fsync_dir(dst_path.parent)
    return ctx.oplog.transition(op.op_id, "applied")


def _staged(op: Operation, ctx: OpContext) -> Operation:
    """Finish a case-only rename: via -> dst."""
    via_path = ctx.root / op.params["via"]
    dst_path = ctx.root / op.params["dst"]
    ctx.fs.rename_noreplace(via_path, dst_path)
    ctx.fs.fsync_dir(dst_path.parent)
    return ctx.oplog.transition(op.op_id, "applied")


def _applied(op: Operation, ctx: OpContext) -> Operation:
    """Verify the destination, then commit the row update in one transaction."""
    dst_rel: str = op.params["dst"]
    dst_path = ctx.root / dst_rel
    st = os.stat(dst_path)
    if st.st_size != op.expect_size or st.st_mtime_ns != op.expect_mtime_ns:
        return ctx.oplog.transition(
            op.op_id, "needs_attention", error=("NEEDS_ATTENTION", "dst mismatch")
        )
    now = ctx.clock()
    size = st.st_size
    mtime_ns = st.st_mtime_ns
    expect_version = op.expect_row_version
    file_id = op.file_id

    def update(conn: object) -> None:
        files_write.update_path(conn, file_id, expect_version, dst_rel, size, mtime_ns, now)

    return ctx.oplog.transition(op.op_id, "committed", extra=update)


def _cleanup_empty_dirs(ctx: OpContext, op: Operation) -> None:
    """Remove emptied source folders up to (not including) the library root.

    Each ``rmdir_if_empty`` only removes an empty directory; a non-empty folder
    or any error stops the walk -- best effort, never a failed op.
    """
    parent = (ctx.root / op.expect_path).parent
    while parent != ctx.root:
        try:
            removed = ctx.fs.rmdir_if_empty(parent)
        except OSError:
            removed = False
        if not removed:
            break
        parent = parent.parent


def _dst_taken(ctx: OpContext, op: Operation, dst_rel: str) -> bool:
    """True when another row (not the one being moved) owns ``dst_rel``'s key."""
    row = ctx.conn.execute(
        "SELECT file_id FROM files WHERE path_key = ? AND file_id != ?",
        (path_key(dst_rel), op.file_id),
    ).fetchone()
    return row is not None


def _existing_ancestor(root: Path, dst_path: Path) -> Path:
    """The closest existing ancestor of ``dst_path`` (never above ``root``)."""
    candidate = dst_path.parent
    while candidate != root and not candidate.exists():
        candidate = candidate.parent
    return candidate


def _missing_parents(root: Path, dst_path: Path) -> list[str]:
    """Folders to create for ``dst_path``, top-most first (root never created)."""
    missing: list[Path] = []
    parent = dst_path.parent
    while parent != root and not parent.exists():
        missing.append(parent)
        parent = parent.parent
    missing.reverse()
    return [str(p) for p in missing]


def _fail(ctx: OpContext, op: Operation, code: str, mark_changed: bool) -> Operation:
    """Fail the op; when ``mark_changed`` the row is flipped to 'changed'."""
    if mark_changed:
        ctx.conn.execute(
            "UPDATE files SET status = 'changed', updated_at = ? WHERE file_id = ?",
            (ctx.clock(), op.file_id),
        )
        ctx.conn.commit()
    return ctx.oplog.transition(op.op_id, "failed", error=(code, code))

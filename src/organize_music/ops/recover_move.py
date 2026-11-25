"""Crash recovery for the move operation (PLAN §6.2 recovery table, P1-14).

After a crash, every non-terminal move must be finished or undone safely:
:func:`recover_move` applies the §6.2 recovery table row by row.  S, V and D
mean that an entry exists at the op's ``src``, ``via`` and ``dst`` names,
checked with :meth:`FsOps.entry_exists` on the *exact* names (a case-only
rename that finished shows D only).  The one action that removes anything is
restricted to the rows where exactly one name exists, and whenever two of the
three names exist at once nothing is removed: an exFAT power cut between
writing the new directory entry and clearing the old one leaves two entries
sharing one cluster chain, and deleting one frees the other's data.  Such
states, like every other ambiguity, stop for a human as ``needs_attention``.
"""

from __future__ import annotations

import os
from pathlib import Path

from organize_music.db import files_write
from organize_music.ops.context import OpContext
from organize_music.ops.move import run_move
from organize_music.ops.oplog_repo import Operation
from organize_music.ops.states import TERMINAL, is_allowed


def recover_move(op: Operation, ctx: OpContext) -> Operation:
    """Drive a non-terminal move op to a terminal state, returning the row.

    ``planned`` moves never touched the disk before their first transition,
    so they are fully retryable and are re-run through :func:`run_move`
    (which rechecks the precondition).  Terminal ops are returned unchanged,
    which makes a second recovery call a no-op.
    """
    op = ctx.oplog.get(op.op_id)
    if op.kind != "move":
        raise ValueError(f"recover_move: op {op.op_id} is a {op.kind!r} op, not a move")
    if op.state == "planned":
        return run_move(op, ctx)
    if op.state in TERMINAL:
        return op
    return _recover_active(op, ctx)


def _recover_active(op: Operation, ctx: OpContext) -> Operation:
    """The §6.2 recovery table for a move in ``intent``, ``staged`` or ``applied``."""
    src = ctx.root / str(op.params["src"])
    dst = ctx.root / str(op.params["dst"])
    via_rel = op.params.get("via")
    via = ctx.root / str(via_rel) if via_rel is not None else None

    s = ctx.fs.entry_exists(src.parent, src.name)
    v = via is not None and ctx.fs.entry_exists(via.parent, via.name)
    d = ctx.fs.entry_exists(dst.parent, dst.name)

    if (s and d) or (s and v) or (v and d):
        # Two entries at once: the doubled-entry danger.  Never remove either
        # name -- deleting one would free the other's shared cluster chain.
        names = "/".join(n for n, flag in (("src", s), ("via", v), ("dst", d)) if flag)
        return _needs_attention(ctx, op, f"two entries exist ({names}); run fsck on the volume")
    if s:
        return _src_only(ctx, op)
    if v:
        return _via_only(ctx, op, via, dst)
    if d:
        return _dst_only(ctx, op, dst)
    return _needs_attention(ctx, op, "file not found at src, via or dst")


def _src_only(ctx: OpContext, op: Operation) -> Operation:
    """S only: the rename never happened; undo the folders and fail the op."""
    _clean_created_dirs(ctx, op)
    if is_allowed(op.kind, op.state, "failed"):
        return ctx.oplog.transition(
            op.op_id, "failed", error=("INTERRUPTED", "rename did not persist")
        )
    # 'staged' and 'applied' have no 'failed' edge (states.ALLOWED), so this
    # picture cannot map onto a legal terminal; stop for a human instead.
    return _needs_attention(ctx, op, "source present from a later state; stopping for a human")


def _via_only(ctx: OpContext, op: Operation, via: Path, dst: Path) -> Operation:
    """V only: case-only rename half done; finish it, then take the applied path."""
    ctx.fs.rename_noreplace(via, dst)
    ctx.fs.fsync_dir(dst.parent)
    op = ctx.oplog.transition(op.op_id, "applied")
    return _dst_only(ctx, op, dst)


def _dst_only(ctx: OpContext, op: Operation, dst: Path) -> Operation:
    """D only: verify the destination, then commit (or stop on a mismatch)."""
    st = os.stat(dst)
    if st.st_size != op.expect_size or st.st_mtime_ns != op.expect_mtime_ns:
        return _needs_attention(ctx, op, "dst mismatch: something else is at the destination")
    if op.state != "applied":
        op = ctx.oplog.transition(op.op_id, "applied")
    now = ctx.clock()
    size = st.st_size
    mtime_ns = st.st_mtime_ns
    file_id = op.file_id
    expect_version = op.expect_row_version
    dst_rel = str(op.params["dst"])

    def update(conn: object) -> None:
        files_write.update_path(conn, file_id, expect_version, dst_rel, size, mtime_ns, now)

    return ctx.oplog.transition(op.op_id, "committed", extra=update)


def _clean_created_dirs(ctx: OpContext, op: Operation) -> None:
    """``rmdir_if_empty`` the ``created_dirs`` in reverse (best effort).

    Each call removes only an empty directory; a folder that still holds
    anything (or any error) stops the walk, never failing the op.
    """
    for d in reversed(op.params.get("created_dirs") or []):
        try:
            removed = ctx.fs.rmdir_if_empty(ctx.root / str(d))
        except OSError:
            removed = False
        if not removed:
            break


def _needs_attention(ctx: OpContext, op: Operation, detail: str) -> Operation:
    """Terminal ``needs_attention`` with an explicit error pair."""
    return ctx.oplog.transition(op.op_id, "needs_attention", error=("NEEDS_ATTENTION", detail))

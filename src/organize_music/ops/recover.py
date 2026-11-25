"""The startup recovery dispatcher (PLAN §6.4, issue b8p.26 / catalogue P1-15).

At startup, before the worker accepts work, every operation in an ACTIVE
state (``intent``, ``staged``, ``parked``, ``applied``) must be driven to a
terminal one. :func:`recover_all` walks :meth:`OplogRepo.active_ops` and
dispatches by kind: a ``move`` goes through :func:`recover_move`; any kind
without a registered recovery (today: ``retag`` -- its recovery registers in
phase 5) stops for a human in terminal ``needs_attention``. The outcome
counts into a :class:`RecoveryReport`.
"""

from __future__ import annotations

from dataclasses import dataclass

from organize_music.ops.context import OpContext
from organize_music.ops.oplog_repo import Operation
from organize_music.ops.recover_move import recover_move


@dataclass(frozen=True)
class RecoveryReport:
    """The outcome of one :func:`recover_all` pass.

    ``committed`` and ``failed`` count the ops that reached those terminal
    states; ``needs_attention`` holds the op ids left for a human, in
    ``active_ops`` order (ascending ``op_id``).
    """

    committed: int
    failed: int
    needs_attention: tuple[int, ...]


def recover_all(ctx: OpContext) -> RecoveryReport:
    """Recover every active op, dispatching by kind, and return the report.

    Each active op is driven to a terminal state: moves through
    :func:`recover_move`, any other kind straight to ``needs_attention``.
    Under the current schema an active op can end only in ``committed``,
    ``failed`` or ``needs_attention``; any other outcome is an unhandled
    state-machine case and fails loudly rather than being silently dropped
    from the report. A second pass over a fully recovered library sees no
    active ops and is a no-op.
    """
    committed = 0
    failed = 0
    attention: list[int] = []
    for op in ctx.oplog.active_ops():
        final = _recover_one(ctx, op)
        if final.state == "committed":
            committed += 1
        elif final.state == "failed":
            failed += 1
        elif final.state == "needs_attention":
            attention.append(final.op_id)
        else:
            raise RuntimeError(
                f"recover_all: op {final.op_id} ended in {final.state!r} "
                f"(expected a committed, failed or needs_attention terminal)"
            )
    return RecoveryReport(committed=committed, failed=failed, needs_attention=tuple(attention))


def _recover_one(ctx: OpContext, op: Operation) -> Operation:
    """Dispatch one active op to its terminal state, by kind."""
    if op.kind == "move":
        return recover_move(op, ctx)
    return _no_recovery(ctx, op)


def _no_recovery(ctx: OpContext, op: Operation) -> Operation:
    """Terminal ``needs_attention`` for a kind this dispatcher cannot finish.

    A ``retag`` op (or any kind without a registered recovery) stops for a
    human instead of being dropped: the ``retag`` recovery registers in
    phase 5, and until then an active retag op is not safe to run or to undo
    automatically.
    """
    return ctx.oplog.transition(
        op.op_id,
        "needs_attention",
        error=("NEEDS_ATTENTION", f"no recovery registered for kind {op.kind!r}"),
    )

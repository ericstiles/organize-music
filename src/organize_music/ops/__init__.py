"""The crash-safe operation log (PLAN §6.2/§6.3).

Exposes the operation states and their allowed transitions, the
:class:`Operation` row model, and :class:`OplogRepo` — the durable,
transition-checked access to the ``operations`` table.
"""

from organize_music.ops.oplog_repo import IllegalTransition, Operation, OplogRepo
from organize_music.ops.states import ACTIVE, TERMINAL, is_allowed

__all__ = [
    "ACTIVE",
    "TERMINAL",
    "IllegalTransition",
    "Operation",
    "OplogRepo",
    "is_allowed",
]

"""The dependencies a mutation op runs against (PLAN §6, issue b8p.22).

:class:`OpContext` bundles the filesystem interface, the operation log, the
write connection and the clock a move op needs, plus the library and work
directories.  It is frozen, so an op receives an immutable view of its
environment.  The two failure classes the engine raises on the disk-check and
the collision-check live here too, next to the context that carries them.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from organize_music.fsops.protocol import FsOps
from organize_music.ops.oplog_repo import OplogRepo


@dataclass(frozen=True)
class OpContext:
    """The environment a move op executes in (PLAN §6.2).

    ``root`` is the library root; ``work_dir`` and ``purge_dir`` live on the
    same device, outside the library; ``fs`` is the injectable filesystem
    (real in production, :class:`FaultyFs`-wrapped in the crash matrix);
    ``oplog`` is the transition-checked operation log; ``conn`` is the writer's
    connection to ``library.db``; ``clock`` supplies UTC timestamps.
    """

    root: Path
    work_dir: Path
    purge_dir: Path
    fs: FsOps
    oplog: OplogRepo
    conn: sqlite3.Connection
    clock: Callable[[], str]


class PreconditionFailed(Exception):
    """The source no longer matches the op's precondition (PLAN §6.1).

    Raised when a re-stat of the source, or a re-read of the row, no longer
    matches ``(expect_size, expect_mtime_ns, expect_row_version)``. The move is
    abandoned and the row is marked ``'changed'``.
    """


class Collision(Exception):
    """The destination is already occupied (PLAN §6.2).

    Raised when the target path is taken, either by a row in ``files`` (its
    collision key) or by an entry on disk. The move is abandoned; nothing is
    moved.
    """

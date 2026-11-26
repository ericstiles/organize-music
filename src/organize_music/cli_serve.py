"""The ``serve`` and ``recover`` commands (PLAN §6.4, catalogue P1-19).

Both take the single-writer lock on ``state/writer.lock`` before touching
``library.db``. ``serve`` holds the lock for the server's lifetime (PLAN
§6.4 "One writer"): ``uvicorn.run`` blocks inside the lock, and it is
released only when the server stops. ``recover`` releases the lock once
the recovery pass has finished. A lock already held by a running server
is reported as "server is running" and the command exits 2.

Under the lock the database is migrated, and -- when the library is
mounted -- the startup recovery drives every active operation to a
terminal state and the report is printed (PLAN §6.4 "Startup"). With the
library not mounted, ``serve`` still starts, read-only: every mutation and
recovery waits with LIBRARY_NOT_MOUNTED; ``recover`` exits 1 because it
could not verify anything.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import uvicorn

from organize_music.config import Config
from organize_music.db import SchemaTooNew, WriterBusy, WriterLock, migrate, open_writer
from organize_music.fsops.protocol import RealFs
from organize_music.ops.context import OpContext
from organize_music.ops.mirror import make_mirror
from organize_music.ops.oplog_repo import OplogRepo
from organize_music.ops.recover import RecoveryReport, recover_all
from organize_music.web.app import create_app

EXIT_OK = 0
EXIT_NEEDS_ATTENTION = 1
EXIT_LOCKED = 2

_LOCK_NAME = "writer.lock"
_DB_NAME = "library.db"
_BACKUPS_DIR = "backups"


def _utcnow() -> str:
    """A UTC timestamp for migration rows and the operation mirror."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _library_root(config: Config) -> Path | None:
    """The library root when mounted (PLAN §6.5), else None.

    Mounted means ``library_mount`` is a real mount point and the library
    directory exists. A missing ``library`` setting is not mounted: with no
    library there is nothing a recovery could verify.
    """
    if config.library is None or not config.library.is_dir():
        return None
    return config.library if os.path.ismount(config.library_mount) else None


def _render_report(report: RecoveryReport) -> str:
    ids = ", ".join(str(op_id) for op_id in report.needs_attention) or "none"
    return f"recover: committed {report.committed}, failed {report.failed}; needs attention: {ids}"


def _op_context(root: Path, config: Config, conn: sqlite3.Connection) -> OpContext:
    """The production context: the real fs, the JSONL mirror, a live clock."""
    clock: Callable[[], str] = _utcnow
    return OpContext(
        root=root,
        work_dir=config.work_dir,
        purge_dir=config.purge_dir,
        fs=RealFs(),
        oplog=OplogRepo(conn, mirror=make_mirror(config.work_dir, clock), clock=clock),
        conn=conn,
        clock=clock,
    )


def _recover(config: Config, conn: sqlite3.Connection) -> RecoveryReport | None:
    """Run the startup recovery when the library is mounted; print the report.

    Returns the report, or None when the library is not mounted: per PLAN
    §6.4 every mutation and recovery then waits with LIBRARY_NOT_MOUNTED.
    """
    root = _library_root(config)
    if root is None:
        return None
    report = recover_all(_op_context(root, config, conn))
    _say(_render_report(report))
    return report


def _migrate(config: Config, conn: sqlite3.Connection) -> bool:
    """Migrate under the lock we hold; report and refuse a too-new schema."""
    db_path = config.state_dir / _DB_NAME
    try:
        migrate(conn, db_path, config.state_dir / _BACKUPS_DIR, _utcnow())
    except SchemaTooNew as exc:
        _say(f"error: {exc}")
        return False
    return True


def run_serve(config: Config) -> int:
    """Lock, migrate, recover if mounted, then serve on the configured bind.

    ``uvicorn.run`` blocks inside the lock, so the writer lock is held for
    the server's lifetime and released only when the server stops.
    """
    config.state_dir.mkdir(parents=True, exist_ok=True)
    db_path = config.state_dir / _DB_NAME
    conn: sqlite3.Connection | None = None
    try:
        with WriterLock(config.state_dir / _LOCK_NAME):
            conn = open_writer(db_path)
            if not _migrate(config, conn):
                return EXIT_LOCKED
            if _recover(config, conn) is None:
                _say("library not mounted: serving read-only (LIBRARY_NOT_MOUNTED)")
            _say(f"serving on http://{config.bind_host}:{config.bind_port}")
            uvicorn.run(create_app(config), host=config.bind_host, port=config.bind_port, workers=1)
            return EXIT_OK
    except WriterBusy as exc:
        _say(str(exc))
        return EXIT_LOCKED
    finally:
        if conn is not None:
            conn.close()


def run_recover(config: Config) -> int:
    """Lock, migrate, recover, print the report, and exit 0 (1 on attention).

    Exits 2 when the writer lock is held (server is running) or the schema
    is too new, and 1 when the library is not mounted (nothing could be
    verified) or when any op was left for a human (needs_attention).
    """
    config.state_dir.mkdir(parents=True, exist_ok=True)
    db_path = config.state_dir / _DB_NAME
    conn: sqlite3.Connection | None = None
    report: RecoveryReport | None = None
    try:
        with WriterLock(config.state_dir / _LOCK_NAME):
            conn = open_writer(db_path)
            if not _migrate(config, conn):
                return EXIT_LOCKED
            report = _recover(config, conn)
    except WriterBusy as exc:
        _say(str(exc))
        return EXIT_LOCKED
    finally:
        if conn is not None:
            conn.close()
    if report is None:
        _say("library not mounted: no recovery ran (LIBRARY_NOT_MOUNTED)")
        return EXIT_NEEDS_ATTENTION
    return EXIT_OK if not report.needs_attention else EXIT_NEEDS_ATTENTION

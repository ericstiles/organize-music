"""Forward-only migrations for library.db, with an online backup first.

library.db is the system of record (PLAN C1). The schema lives in numbered SQL
files ``NNNN_name.sql`` under this package's ``migrations`` directory; they
apply in ascending version order and are recorded in ``PRAGMA user_version``.
A DB newer than the code (``user_version`` or a yoyo id the code does not
ship) refuses to open (``SchemaTooNew``), untouched. Before applying onto an
existing schema the runner takes an online backup. Nothing removes a table.

Pending migrations are applied through ``yoyo-migrations`` 9.0.0, which
records each in its own ``_yoyo_migration`` table; yoyo opens its own
connection and the caller's ``conn`` observes the committed changes. A DB
made by the old runner (a ``user_version`` but no ``_yoyo_migration`` table)
is adopted: its applied migrations are marked in yoyo without being re-run,
so 0001 runs on it exactly once. ``migrate`` optionally takes a ``lock_path``
and, when given, runs under the single-writer lock (db/connection.py).
"""

import contextlib
import re
import sqlite3
from pathlib import Path

import yoyo
from yoyo.migrations import Migration

from organize_music.db.connection import WriterLock
from organize_music.db.migration_checksums import (
    MigrationChanged,
    ensure_checksum_table,
    record_checksum,
    verify_checksums,
)

__all__ = ["MigrationChanged", "SchemaTooNew", "available", "migrate"]

# The migrations directory shipped with the package.
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_FILE = re.compile(r"^(\d+)_")
# yoyo's table of applied migrations (plural in the docs, singular on disk).
_YOYO_TABLE = "_yoyo_migration"


class SchemaTooNew(Exception):
    """The database's ``user_version`` is newer than the code knows about."""


def available(migrations_dir: Path | None = None) -> list[tuple[int, str]]:
    """Return ``(version, sql)`` pairs from ``NNNN_name.sql`` files, sorted by version."""
    directory = _MIGRATIONS_DIR if migrations_dir is None else migrations_dir
    found: list[tuple[int, str]] = []
    for path in directory.glob("*.sql"):
        match = _FILE.match(path.name)
        if match is None:
            continue
        version = int(match.group(1))
        found.append((version, path.read_text(encoding="utf-8")))
    found.sort(key=lambda pair: pair[0])
    return found


def _version_of(migration: Migration) -> int:
    """The numeric version encoded in a yoyo migration id, e.g. ``0002_fake`` -> 2."""
    return int(migration.id.split("_", 1)[0])


def _yoyo_manages(conn: sqlite3.Connection) -> bool:
    """True if the DB already has yoyo's applied-migration table."""
    row = conn.execute(
        f"SELECT 1 FROM sqlite_master WHERE type='table' AND name='{_YOYO_TABLE}'"
    ).fetchone()
    return row is not None


def _applied_ids(conn: sqlite3.Connection) -> set[str]:
    """Migration ids yoyo has already recorded in the DB (a plain read)."""
    return {row[0] for row in conn.execute(f"SELECT migration_id FROM {_YOYO_TABLE}").fetchall()}


def _unknown_applied(conn: sqlite3.Connection, directory: Path) -> set[str]:
    """Applied yoyo ids that have no matching migration file (a too-new schema).

    A plain SELECT: takes no lock, writes nothing -- the DB stays byte-identical."""
    if not _yoyo_manages(conn):
        return set()
    known = {path.stem for path in directory.glob("*.sql") if _FILE.match(path.name)}
    return _applied_ids(conn) - known


def _backup(conn: sqlite3.Connection, backups_dir: Path, old_version: int, now: str) -> None:
    """Copy the live database to ``backups_dir/library-v<old>-<now>.db`` before migrating."""
    backups_dir.mkdir(parents=True, exist_ok=True)
    dest = backups_dir / f"library-v{old_version}-{now}.db"
    target = sqlite3.connect(dest)
    try:
        conn.backup(target)
        target.commit()
    finally:
        target.close()


def _highest_applied(conn: sqlite3.Connection) -> int:
    """The highest migration version yoyo has recorded; a plain read.

    Read from the record, not ``user_version``, so a crash-lagged value is repaired."""
    rows = conn.execute(f"SELECT migration_id FROM {_YOYO_TABLE}").fetchall()
    if not rows:
        return 0
    return max(int(migration_id.split("_", 1)[0]) for migration_id in (r[0] for r in rows))


def migrate(
    conn: sqlite3.Connection,
    db_path: Path,
    backups_dir: Path,
    now: str,
    migrations_dir: Path | None = None,
    lock_path: Path | None = None,
) -> int:
    """Apply pending migrations to ``conn`` and return the final ``user_version``.

    A database whose ``user_version`` exceeds the newest available file raises
    ``SchemaTooNew`` and is left untouched. When migrations are pending on a DB
    that already has a schema (``user_version > 0``), an online backup is taken
    first; each pending file is then applied through yoyo in its own
    transaction, and afterwards ``user_version`` is set to the highest version
    yoyo has recorded, which also repairs a value left lagging by a crash. A DB
    made by the old runner (a ``user_version`` but no yoyo table) is adopted:
    its applied migrations are marked in yoyo without being run. yoyo's
    connection is closed when the call returns.

    When ``lock_path`` is given the call runs under the single-writer lock:
    ``WriterLock`` is acquired on it before anything happens and released on
    every exit (success, refusal, crash). A second concurrent ``migrate()`` on
    the same ``lock_path`` -- this process or another -- is refused with
    ``WriterBusy`` before touching the database. A caller that already holds
    the writer lock (e.g. the server) omits ``lock_path``.
    """
    with contextlib.ExitStack() as stack:
        if lock_path is not None:
            # The parent (state/) may not exist on a fresh install.
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            stack.enter_context(WriterLock(lock_path))
        user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
        migrations = available(migrations_dir)
        max_available = migrations[-1][0] if migrations else 0
        pending = [(v, sql) for (v, sql) in migrations if v > user_version]
        if user_version > max_available:
            raise SchemaTooNew(
                f"database user_version {user_version} is newer than the "
                f"code's schema version {max_available}"
            )
        directory = _MIGRATIONS_DIR if migrations_dir is None else migrations_dir
        # A DB that yoyo already applied a migration the code does not ship is
        # too new as well: refuse before any backup or write.
        unknown = _unknown_applied(conn, directory)
        if unknown:
            raise SchemaTooNew(
                "database has applied migration(s) the code does not know: "
                + ", ".join(sorted(unknown))
            )
        # Verify applied migrations against the shipped files before any backup
        # or write: a mismatch raises MigrationChanged and touches nothing.
        applied = _applied_ids(conn) if _yoyo_manages(conn) else set()
        id_to_path = {p.stem: str(p) for p in directory.glob("*.sql") if _FILE.match(p.name)}
        verify_checksums(conn, applied, id_to_path, now)
        # A DB the old runner made (a version but no yoyo table) is adopted:
        # its applied migrations are marked in yoyo WITHOUT being run.
        if not pending and not (user_version > 0 and not _yoyo_manages(conn)):
            return user_version
        if pending and user_version > 0:
            _backup(conn, backups_dir, user_version, now)
        yoyo_migrations = yoyo.read_migrations(str(directory))
        to_adopt = [m for m in yoyo_migrations if _version_of(m) <= user_version]
        backend = yoyo.get_backend(f"sqlite:///{db_path}")
        try:
            with backend.lock():
                # Adoption: record the migrations the old runner already applied
                # in yoyo without executing them, so their SQL runs once.
                if user_version > 0 and not _yoyo_manages(conn):
                    backend.mark_migrations(to_adopt)
                # Pending comes from yoyo's own state, not user_version: a crash
                # can leave user_version behind a migration yoyo already
                # recorded, and recomputing from it would re-apply and fail.
                # The checksum table is runner-created, not a numbered migration.
                ensure_checksum_table(conn)
                for migration in backend.to_apply(yoyo_migrations):
                    backend.apply_one(migration)
                    record_checksum(conn, migration.id, migration.path, now)
                    # Commit the checksum before the next apply_one runs on
                    # yoyo's own connection: an open write transaction blocks.
                    conn.commit()
                # user_version = highest version yoyo has recorded: this
                # advances it and repairs a value left lagging by a crash.
                highest = _highest_applied(conn)
                conn.execute(f"PRAGMA user_version = {highest}")
                conn.commit()
        finally:
            backend.connection.close()
    return int(conn.execute("PRAGMA user_version").fetchone()[0])

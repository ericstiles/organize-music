"""Forward-only migrations for library.db, with an online backup first.

library.db is the system of record (PLAN C1). The schema lives in numbered SQL
files ``NNNN_name.sql`` under this package's ``migrations`` directory; they are
applied in ascending version order and recorded in ``PRAGMA user_version``.
Nothing ever removes a table on a version mismatch, and a DB whose
``user_version`` exceeds the newest file refuses to open (``SchemaTooNew``).
Before applying any migration onto an existing schema the runner takes an online
backup so a bad migration can be rolled back from disk.

Pending migrations are applied through ``yoyo-migrations`` 9.0.0, which records
each applied migration in its own ``_yoyo_migration`` table. yoyo opens its own
connection to the same file; the caller's ``conn`` observes the committed
changes. A DB made by the old runner (``user_version`` > 0 but no
``_yoyo_migration`` table) is adopted: its already-applied migrations are
marked in yoyo without being re-run, so 0001 runs on it exactly once.
"""

import re
import sqlite3
from pathlib import Path

import yoyo
from yoyo.migrations import Migration

__all__ = ["SchemaTooNew", "available", "migrate"]

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


def migrate(
    conn: sqlite3.Connection,
    db_path: Path,
    backups_dir: Path,
    now: str,
    migrations_dir: Path | None = None,
) -> int:
    """Apply pending migrations to ``conn`` and return the final ``user_version``.

    A database whose ``user_version`` exceeds the newest available file raises
    ``SchemaTooNew`` and is left untouched. When migrations are pending on a DB
    that already has a schema (``user_version > 0``), an online backup is taken
    first. Each pending file is then applied through yoyo in its own transaction
    and the ``user_version`` is bumped to that file's version. A DB made by the
    old runner (a ``user_version`` but no yoyo table) is adopted: its applied
    migrations are marked in yoyo without being run. yoyo's connection is closed
    when the call returns.
    """
    user_version = int(conn.execute("PRAGMA user_version").fetchone()[0])
    migrations = available(migrations_dir)
    max_available = migrations[-1][0] if migrations else 0
    pending = [(v, sql) for (v, sql) in migrations if v > user_version]
    if user_version > max_available:
        raise SchemaTooNew(
            f"database user_version {user_version} is newer than the "
            f"code's schema version {max_available}"
        )
    # A DB the old runner made (a version but no yoyo table) is adopted: its
    # already-applied migrations are marked in yoyo WITHOUT being run, so 0001
    # is never re-executed on top of the existing schema.
    if pending and user_version > 0:
        _backup(conn, backups_dir, user_version, now)
    if not pending and not (user_version > 0 and not _yoyo_manages(conn)):
        return user_version
    directory = _MIGRATIONS_DIR if migrations_dir is None else migrations_dir
    yoyo_migrations = yoyo.read_migrations(str(directory))
    to_apply = [m for m in yoyo_migrations if _version_of(m) > user_version]
    to_adopt = [m for m in yoyo_migrations if _version_of(m) <= user_version]
    backend = yoyo.get_backend(f"sqlite:///{db_path}")
    try:
        with backend.lock():
            # Adoption: record the migrations the old runner already applied in
            # yoyo without executing them, so their SQL runs on this DB once.
            if user_version > 0 and not _yoyo_manages(conn):
                backend.mark_migrations(to_adopt)
            # Apply the remaining pending migrations, each in its own
            # transaction, and bump user_version as they land.
            for migration in to_apply:
                backend.apply_one(migration)
                conn.execute(f"PRAGMA user_version = {_version_of(migration)}")
                conn.commit()
    finally:
        backend.connection.close()
    return int(conn.execute("PRAGMA user_version").fetchone()[0])

"""Forward-only migrations for library.db, with an online backup first.

library.db is the system of record (PLAN C1). The schema lives in numbered SQL
files ``NNNN_name.sql`` under this package's ``migrations`` directory; they are
applied in ascending version order and recorded in ``PRAGMA user_version``.
Nothing ever removes a table on a version mismatch, and a DB whose
``user_version`` exceeds the newest file refuses to open (``SchemaTooNew``).
Before applying any migration onto an existing schema the runner takes an online
backup so a bad migration can be rolled back from disk.
"""

import re
import sqlite3
from pathlib import Path

__all__ = ["SchemaTooNew", "available", "migrate"]

# The migrations directory shipped with the package.
_MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_FILE = re.compile(r"^(\d+)_")


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
    first. Each pending file is then applied in its own transaction and the
    ``user_version`` is bumped to that file's version.
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
    if pending and user_version > 0:
        _backup(conn, backups_dir, user_version, now)
    for version, sql in pending:
        conn.executescript(sql)
        conn.execute(f"PRAGMA user_version = {version}")
        conn.commit()
    return int(conn.execute("PRAGMA user_version").fetchone()[0])

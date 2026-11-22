"""Content checksums for applied migrations.

yoyo-migrations records only the *id* of each applied migration, so an edited
migration file is invisible. The runner keeps its own ``migration_checksums``
table holding the sha256 of every migration file's bytes at the moment it
applied. On open the runner verifies those checksums against the shipped files:
a mismatch raises :class:`MigrationChanged` and touches nothing; an applied id
with no checksum row (a crash between yoyo's record and ours, or a DB made by an
earlier step) is backfilled with the current file's hash and a warning is logged.
"""

import hashlib
import logging
import sqlite3
from pathlib import Path

__all__ = [
    "CHECKSUM_TABLE",
    "MigrationChanged",
    "ensure_checksum_table",
    "record_checksum",
    "verify_checksums",
]

CHECKSUM_TABLE = "migration_checksums"

_log = logging.getLogger(__name__)


class MigrationChanged(Exception):
    """An applied migration's content no longer matches the shipped file."""

    def __init__(self, migration_id: str) -> None:
        super().__init__(migration_id)
        self.migration_id = migration_id


def ensure_checksum_table(conn: sqlite3.Connection) -> None:
    """Create the runner's checksum table if it is absent.

    Created by the runner rather than a numbered migration: it is metadata about
    the migration process, not part of the library schema.
    """
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {CHECKSUM_TABLE} ("
        "migration_id TEXT PRIMARY KEY, "
        "sha256 TEXT NOT NULL, "
        "applied_at TEXT NOT NULL)"
    )


def record_checksum(conn: sqlite3.Connection, migration_id: str, path: str, now: str) -> None:
    """Record the sha256 of ``path``'s bytes for ``migration_id``.

    Called after a migration has applied, so a migration that fails part-way
    never gets a row. The id is the primary key: a re-run is a no-op.
    """
    ensure_checksum_table(conn)
    digest = hashlib.sha256(_path(path).read_bytes()).hexdigest()
    conn.execute(
        f"INSERT OR IGNORE INTO {CHECKSUM_TABLE} "
        "(migration_id, sha256, applied_at) VALUES (?, ?, ?)",
        (migration_id, digest, now),
    )


def verify_checksums(
    conn: sqlite3.Connection,
    applied_ids: set[str],
    id_to_path: dict[str, str],
    now: str,
) -> None:
    """Check every applied migration's stored checksum against its shipped file.

    For each applied id that has a checksum row, compare the stored sha256 with
    the shipped file's current bytes; a mismatch raises :class:`MigrationChanged`
    and nothing is written. An applied id with no checksum row (a crash between
    yoyo's record and ours, or a DB made by an earlier step) is backfilled with
    the current file's hash and a warning is logged.
    """
    if not applied_ids:
        return
    ensure_checksum_table(conn)
    stored = {
        row[0]: row[1]
        for row in conn.execute(f"SELECT migration_id, sha256 FROM {CHECKSUM_TABLE}").fetchall()
    }
    backfilled = False
    for migration_id in sorted(applied_ids):
        path = id_to_path.get(migration_id)
        if path is None:
            # An applied id with no matching file is refused earlier as
            # SchemaTooNew, so there is nothing to check or backfill here.
            continue
        current = hashlib.sha256(_path(path).read_bytes()).hexdigest()
        if migration_id in stored:
            if stored[migration_id] != current:
                raise MigrationChanged(migration_id)
        else:
            record_checksum(conn, migration_id, path, now)
            _log.warning(
                "checksum for applied migration %s was missing; backfilled with the current file",
                migration_id,
            )
            backfilled = True
    # Commit the backfill so the caller's connection releases its write lock
    # before yoyo opens its own connection to the same file (an uncommitted
    # transaction would otherwise block yoyo and deadlock).
    if backfilled:
        conn.commit()


def _path(path: str) -> Path:
    """The ``Path`` for a migration id's file, resolving a relative location.

    yoyo's ``Migration.path`` is a ``str``; wrap it for ``.read_bytes()``.
    """
    return Path(path)

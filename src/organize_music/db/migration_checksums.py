"""Content checksums for applied migrations.

yoyo-migrations records only the *id* of each applied migration, so an edited
migration file is invisible. The runner keeps its own ``migration_checksums``
table holding the sha256 of every migration file's bytes at the moment it
applied. Step 4 of the yoyo effort will verify those checksums on open; this
module is the record-keeping half of that guard.
"""

import hashlib

__all__ = ["CHECKSUM_TABLE", "ensure_checksum_table", "record_checksum"]

CHECKSUM_TABLE = "migration_checksums"


def ensure_checksum_table(conn) -> None:
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


def record_checksum(conn, migration_id: str, path: str, now: str) -> None:
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


def _path(path: str):
    """The ``Path`` for a migration id's file, resolving a relative location.

    yoyo's ``Migration.path`` is a ``str``; wrap it for ``.read_bytes()``.
    """
    from pathlib import Path

    return Path(path)

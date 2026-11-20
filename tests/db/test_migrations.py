"""Tests for the migration runner with online backup (PLAN §5, issue b8p.5).

library.db is the system of record. Migrations are forward-only numbered SQL
files in ``db/migrations/NNNN_name.sql``; a DB newer than the code refuses to
open (``SchemaTooNew``), and before applying any migration on an existing
schema the runner takes an online backup. Nothing ever drops a table.
"""

import sqlite3
from pathlib import Path

import pytest

from organize_music.db.migrations import SchemaTooNew, available, migrate

# A token that appears in no other column, so an FTS match isolates the artist.
ARTIST = "Marblehead"
NEW_ARTIST = "OtherBand"


def open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _file_values(**overrides: object) -> dict[str, object]:
    """A fully-populated, valid ``files`` row; override any column to probe it."""
    values: dict[str, object] = {
        "path": "Carbon Leaf/Echo Echo/01 Learn To Fly.mp3",
        "path_key": "carbon leaf/echo echo/01 learn to fly.mp3",
        "last_path": "Carbon Leaf/Echo Echo/01 Learn To Fly.mp3",
        "status": "present",
        "kind": "audio",
        "size": 1024,
        "mtime_ns": 1_700_000_000_000_000_000,
        "ext": "mp3",
        "raw_tags": None,
        "read_error": None,
        "duration_seconds": 4.0,
        "bitrate_kbps": 192,
        "artist": ARTIST,
        "artist_src": "tag",
        "album_artist": "Carbon Leaf",
        "album_artist_src": "tag",
        "album": "Echo Echo",
        "album_src": "tag",
        "title": "Learn To Fly",
        "title_src": "tag",
        "track_number": "1",
        "track_number_src": "tag",
        "disc_number": "1",
        "disc_number_src": "tag",
        "year": "2001",
        "year_src": "tag",
        "genre": "Rock",
        "genre_src": "tag",
        "audio_hash": None,
        "hash_kind": None,
        "hash_size": None,
        "hash_mtime_ns": None,
        "row_version": 1,
        "first_seen_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-01T00:00:00Z",
    }
    values.update(overrides)
    return values


def insert_file(conn: sqlite3.Connection, **overrides: object) -> int:
    vals = _file_values(**overrides)
    cols = ", ".join(vals)
    placeholders = ", ".join("?" for _ in vals)
    cur = conn.execute(f"INSERT INTO files ({cols}) VALUES ({placeholders})", list(vals.values()))
    conn.commit()
    return int(cur.lastrowid)


def objects(conn: sqlite3.Connection) -> set[tuple[str, str]]:
    rows = conn.execute(
        "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
    ).fetchall()
    return {(r["type"], r["name"]) for r in rows}


def test_fresh_db_reaches_version_1_with_all_schema_objects(tmp_path):
    path = tmp_path / "library.db"
    conn = open_conn(path)
    try:
        version = migrate(conn, path, tmp_path / "backups", "2026-01-01T00:00:00Z")
        assert version == 1
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 1
        present = objects(conn)
        # Tables from PLAN §5.
        for table in ("settings", "files", "batches", "operations", "events", "jobs"):
            assert ("table", table) in present
        # The songs view and the FTS virtual table.
        assert ("view", "songs") in present
        assert ("table", "files_fts") in present
        # A representative index and the FTS sync triggers.
        assert ("index", "files_path_key") in present
        assert ("trigger", "files_ai") in present
        assert ("trigger", "files_au") in present
        assert ("trigger", "files_ad") in present
        # No backups on a fresh DB (nothing to back up yet): the dir may not
        # even exist because the runner only creates it when a backup is taken.
        backups = tmp_path / "backups"
        assert not backups.exists() or list(backups.iterdir()) == []
    finally:
        conn.close()


def test_migrate_twice_is_a_noop(tmp_path):
    path = tmp_path / "library.db"
    conn = open_conn(path)
    try:
        assert migrate(conn, path, tmp_path / "backups", "2026-01-01T00:00:00Z") == 1
        before = conn.execute("PRAGMA user_version").fetchone()[0]
        second = migrate(conn, path, tmp_path / "backups", "2026-01-02T00:00:00Z")
        assert second == 1
        after = conn.execute("PRAGMA user_version").fetchone()[0]
        assert before == after == 1
    finally:
        conn.close()


def test_user_version_newer_than_code_refuses_to_open(tmp_path):
    path = tmp_path / "library.db"
    conn = open_conn(path)
    conn.execute("PRAGMA user_version = 99")
    conn.commit()
    backups = tmp_path / "backups"
    with pytest.raises(SchemaTooNew):
        migrate(conn, path, backups, "2026-01-01T00:00:00Z")
    # The DB is untouched: still version 99, and no backup was taken.
    assert conn.execute("PRAGMA user_version").fetchone()[0] == 99
    assert not backups.exists() or list(backups.iterdir()) == []
    conn.close()


def test_backup_is_taken_before_a_pending_migration_applies(tmp_path):
    """A second migration on an existing schema is preceded by an online backup."""
    path = tmp_path / "library.db"
    now = "2026-03-01T12:00:00Z"
    backups = tmp_path / "backups"

    conn = open_conn(path)
    try:
        # Fresh DB, real migrations dir: version 0 -> 1, no backup (old version 0).
        assert migrate(conn, path, backups, now) == 1

        # A temporary migrations dir with the real 0001 plus a fake 0002 marker.
        fake_dir = tmp_path / "migrations"
        fake_dir.mkdir()
        (fake_dir / "0001_initial.sql").write_text(
            available()[0][1],
            encoding="utf-8",  # the real 0001_initial text
        )
        (fake_dir / "0002_fake.sql").write_text(
            "CREATE TABLE marker_0002 (x INTEGER);\n", encoding="utf-8"
        )

        # Second migrate picks up the pending 0002: user_version 1 > 0, so a
        # backup is taken BEFORE 0002 applies.
        assert migrate(conn, path, backups, now, migrations_dir=fake_dir) == 2
        backup = backups / f"library-v1-{now}.db"
        assert backup.exists()
        # 0002's table is in the live DB ...
        assert "marker_0002" in {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master").fetchall()
        }
        # ... but not in the backup, proving the backup preceded 0002.
        backup_conn = open_conn(backup)
        try:
            names = {r[0] for r in backup_conn.execute("SELECT name FROM sqlite_master").fetchall()}
            assert "marker_0002" not in names
        finally:
            backup_conn.close()
    finally:
        conn.close()


def test_status_gone_with_a_path_fails_the_check(tmp_path):
    path = tmp_path / "library.db"
    conn = open_conn(path)
    try:
        migrate(conn, path, tmp_path / "backups", "2026-01-01T00:00:00Z")
        with pytest.raises(sqlite3.IntegrityError):
            insert_file(conn, status="gone", path="some/where.mp3")
    finally:
        conn.close()


def test_casefolded_path_keys_collide_in_the_unique_index(tmp_path):
    path = tmp_path / "library.db"
    conn = open_conn(path)
    try:
        migrate(conn, path, tmp_path / "backups", "2026-01-01T00:00:00Z")
        insert_file(conn, path="a", path_key="a".casefold())
        # 'A'.casefold() == 'a': a second row with the same collision key must fail.
        with pytest.raises(sqlite3.IntegrityError):
            insert_file(conn, path="A", path_key="A".casefold())
    finally:
        conn.close()


def test_fts_syncs_with_insert_and_update(tmp_path):
    path = tmp_path / "library.db"
    conn = open_conn(path)
    try:
        migrate(conn, path, tmp_path / "backups", "2026-01-01T00:00:00Z")
        file_id = insert_file(conn, artist=ARTIST)
        # The row is findable in the FTS index by its artist.
        found = conn.execute(
            "SELECT rowid FROM files_fts WHERE files_fts MATCH ?", (ARTIST,)
        ).fetchall()
        assert [r["rowid"] for r in found] == [file_id]
        # After the artist changes, the old token no longer matches.
        conn.execute("UPDATE files SET artist = ? WHERE file_id = ?", (NEW_ARTIST, file_id))
        conn.commit()
        found_after = conn.execute(
            "SELECT rowid FROM files_fts WHERE files_fts MATCH ?", (ARTIST,)
        ).fetchall()
        assert found_after == []
        # The new artist is indexed.
        found_new = conn.execute(
            "SELECT rowid FROM files_fts WHERE files_fts MATCH ?", (NEW_ARTIST,)
        ).fetchall()
        assert [r["rowid"] for r in found_new] == [file_id]
    finally:
        conn.close()

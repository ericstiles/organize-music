"""Tests for the ``/healthz`` probe (issue organize_music-0bi, PLAN §9.2).

``db`` must reflect the real schema, not just a readable SQLite file: a
zero-byte file and an unmigrated database (tables, but no ``files`` table)
cannot serve any page, so they report ``db: false`` and ``ok: false``.
``ok`` is true only when every component is healthy.
"""

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from organize_music.config import load_config
from organize_music.db import migrate
from organize_music.web.app import create_app

NOW = "2026-01-01T00:00:00Z"


def client(tmp_path: Path) -> TestClient:
    """A TestClient over a state_dir at ``tmp_path`` (library.db optional)."""
    overrides = {"state_dir": tmp_path, "library_mount": tmp_path}
    return TestClient(create_app(load_config(None, overrides=overrides)))


def migrated_db(tmp_path: Path) -> Path:
    """Create ``tmp_path/library.db`` and run the migrations (zero rows)."""
    db = tmp_path / "library.db"
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn, db, tmp_path / "backups", NOW)
    conn.close()
    return db


def test_healthz_zero_byte_db_reports_db_false_and_ok_false(tmp_path: Path) -> None:
    # A 0-byte library.db is a valid empty database with no schema: it cannot
    # serve /files, so the probe must report db: false and ok: false.
    (tmp_path / "library.db").write_bytes(b"")
    resp = client(tmp_path).get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] is False
    assert body["ok"] is False
    assert body["library_mounted"] is True


def test_healthz_unmigrated_db_reports_db_false(tmp_path: Path) -> None:
    # A database with tables but no ``files`` table cannot serve any page.
    db = tmp_path / "library.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.close()
    assert db.is_file()
    resp = client(tmp_path).get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] is False
    assert body["ok"] is False


def test_healthz_migrated_empty_db_reports_db_true(tmp_path: Path) -> None:
    # A migrated database whose ``files`` table is empty still has the schema
    # and can serve every page: db: true and ok: true.
    migrated_db(tmp_path)
    resp = client(tmp_path).get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["db"] is True
    assert body["ok"] is True
    assert body["library_mounted"] is True

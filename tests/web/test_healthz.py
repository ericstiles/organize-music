"""Tests for the ``/healthz`` probe (PLAN §9.2).

``db`` must reflect the real schema, not just a readable SQLite file
(issue organize_music-0bi): a zero-byte file and an unmigrated database
(tables, but no ``files`` table) cannot serve any page, so they report
``db: false`` and ``ok: false``.

``library_mounted`` must reflect a real mount, not the mere existence of the
configured folder (issue organize_music-g5v): after the drive is unmounted the
mount point lingers as an empty directory, and monitoring has to see the outage.

``ok`` is true only when every component is healthy.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from organize_music.config import load_config
from organize_music.db import migrate
from organize_music.web.app import create_app

NOW = "2026-01-01T00:00:00Z"


@pytest.fixture
def mounted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the drive mounted at ``tmp_path``: a plain tmp dir is not a mount point."""

    def fake_ismount(path: str | Path) -> bool:
        return str(path) == str(tmp_path)

    monkeypatch.setattr("os.path.ismount", fake_ismount)


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


@pytest.mark.usefixtures("mounted")
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


@pytest.mark.usefixtures("mounted")
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


@pytest.mark.usefixtures("mounted")
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


def _client(tmp_path: Path, mount: Path) -> TestClient:
    """A TestClient over an empty state_dir with the given ``library_mount``."""
    overrides = {"state_dir": tmp_path, "library_mount": mount}
    app = create_app(load_config(None, overrides=overrides))
    return TestClient(app)


def test_healthz_plain_dir_is_not_mounted(tmp_path: Path) -> None:
    # A plain directory that exists but is not a mount point (the leftover
    # folder after the drive was unmounted) must report library_mounted false.
    c = _client(tmp_path, tmp_path)
    resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["library_mounted"] is False


def test_healthz_reports_mounted_when_ismount_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate the drive being mounted: os.path.ismount is true for the
    # configured path.
    def fake_ismount(path: str | Path) -> bool:
        return str(path) == str(tmp_path)

    monkeypatch.setattr("os.path.ismount", fake_ismount)
    c = _client(tmp_path, tmp_path)
    resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["library_mounted"] is True


def test_healthz_missing_mount_dir_is_not_mounted(tmp_path: Path) -> None:
    # A missing mount path must report library_mounted false, not crash.
    c = _client(tmp_path, tmp_path / "no-such-mount")
    resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["library_mounted"] is False


def test_healthz_reports_unmounted_when_ismount_false_for_mounted_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The opposite simulation: the folder exists but ismount says no (the
    # drive was unmounted, the empty mount folder remains).
    monkeypatch.setattr("os.path.ismount", lambda path: False)
    c = _client(tmp_path, tmp_path)
    resp = c.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["library_mounted"] is False

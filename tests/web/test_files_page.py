"""Tests for the first web layer (issue b8p.29, PLAN §9.1, §9.5).

``create_app`` builds a FastAPI app over library.db: a JSON ``/healthz``, a
redirect from ``/`` to ``/files``, and a paged ``/files`` list (100 rows a
page, server-side paging over the ``files`` table). Pages are Jinja2-rendered
with autoescape on, so untrusted tag values can never inject markup.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from organize_music.config import load_config
from organize_music.db import migrate
from organize_music.db.files_repo import FileRow, FilesRepo
from organize_music.models import FileRecord
from organize_music.web.app import create_app

NOW = "2026-01-01T00:00:00Z"


def open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def record(name: str) -> FileRecord:
    return FileRecord(path=name, size=1024, mtime_ns=1_700, ext="mp3")


def migrated_populated(tmp_path: Path, n: int = 0, titles: dict[int, str] | None = None) -> Path:
    """Create tmp_path/library.db, migrate it, and insert ``n`` rows.

    ``titles`` maps a row index to a title to write into that row so a row's
    ``title`` column carries a real (untrusted) value to render.
    """
    db = tmp_path / "library.db"
    conn = open_conn(db)
    migrate(conn, db, tmp_path / "backups", NOW)
    repo = FilesRepo(conn)
    for i in range(n):
        name = f"artist/album/{i:03d}-Song_{i}.mp3"
        repo.insert_scanned(record(name), "audio", NOW)
    for idx, title in (titles or {}).items():
        row = conn.execute(
            "SELECT file_id FROM files ORDER BY path_key, file_id LIMIT 1 OFFSET ?", (idx,)
        ).fetchone()
        conn.execute("UPDATE files SET title = ? WHERE file_id = ?", (title, row["file_id"]))
    repo.commit()
    conn.close()
    return db


def client(tmp_path: Path, n: int = 0, titles: dict[int, str] | None = None) -> TestClient:
    """A TestClient over a migrated library.db holding ``n`` rows."""
    migrated_populated(tmp_path, n, titles)
    overrides = {"state_dir": tmp_path, "library_mount": tmp_path}
    app = create_app(load_config(None, overrides=overrides))
    return TestClient(app)


def bare_client(tmp_path: Path) -> tuple[TestClient, Path]:
    """A TestClient over a state_dir with NO library.db, paired with the db path.

    No database is created here, so a read-only ``/files`` request must not
    create one (see organize_music-8gz).
    """
    db = tmp_path / "library.db"
    overrides = {"state_dir": tmp_path, "library_mount": tmp_path}
    app = create_app(load_config(None, overrides=overrides))
    return TestClient(app), db


def test_files_missing_db_does_not_create_it(tmp_path: Path) -> None:
    # A fresh state_dir has no library.db; a read-only request must not create
    # one, and must answer 503 rather than 500 with a traceback.
    c, db = bare_client(tmp_path)
    resp = c.get("/files")
    assert resp.status_code == 503
    assert not db.exists(), "GET /files must not create library.db"
    assert "scan" in resp.text.lower()
    assert "500" not in resp.text


def test_files_zero_byte_db_is_503(tmp_path: Path) -> None:
    # A 0-byte library.db (an empty file is a valid empty database) has no
    # ``files`` table, so /files must answer 503, not 500.
    c, db = bare_client(tmp_path)
    db.write_bytes(b"")
    resp = c.get("/files")
    assert resp.status_code == 503
    assert "scan" in resp.text.lower()


def test_healthz_returns_200_json(tmp_path: Path) -> None:
    c = client(tmp_path)
    resp = c.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["db"] is True
    assert body["library_mounted"] is True


def test_healthz_reports_db_false_when_library_db_missing(tmp_path: Path) -> None:
    # No library.db was created, so the DB probe must report down, not crash.
    overrides = {"state_dir": tmp_path, "library_mount": tmp_path}
    app = create_app(load_config(None, overrides=overrides))
    resp = TestClient(app).get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["db"] is False


def test_healthz_reports_db_false_for_corrupt_file(tmp_path: Path) -> None:
    # A file at library.db that is not a valid SQLite database reports down.
    (tmp_path / "library.db").write_text("not a database", encoding="utf-8")
    overrides = {"state_dir": tmp_path, "library_mount": tmp_path}
    app = create_app(load_config(None, overrides=overrides))
    resp = TestClient(app).get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["db"] is False


def test_files_shows_rows(tmp_path: Path) -> None:
    c = client(tmp_path, n=3)
    resp = c.get("/files")
    assert resp.status_code == 200
    text = resp.text
    # Three rows rendered, each with a stable data-file-id attribute.
    assert text.count("data-file-id=") == 3
    assert "artist/album/000-Song_0.mp3" in text


def test_files_page_two_of_150_shows_50(tmp_path: Path) -> None:
    c = client(tmp_path, n=150)
    resp = c.get("/files?page=2")
    assert resp.status_code == 200
    # 150 rows, 100 a page -> page 2 holds the remaining 50.
    assert resp.text.count("data-file-id=") == 50
    # ...and page 1 held the first 100.
    assert c.get("/files?page=1").text.count("data-file-id=") == 100


def test_files_page_zero_and_non_int_are_422(tmp_path: Path) -> None:
    c = client(tmp_path, n=5)
    assert c.get("/files?page=0").status_code == 422
    assert c.get("/files?page=abc").status_code == 422


def test_files_out_of_range_page_redirects_to_last_page(tmp_path: Path) -> None:
    # 150 rows -> 2 pages. page=999 must not render an empty table titled
    # "page 999 of 2" with a Prev link to 998; it must bounce to the real
    # last page (303).
    c = client(tmp_path, n=150)
    resp = c.get("/files?page=999", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/files?page=2"
    # ...and the redirect target renders the (non-empty) last page.
    landed = c.get("/files?page=2")
    assert landed.status_code == 200
    assert landed.text.count("data-file-id=") == 50
    assert "page 2 of 2" in landed.text


def test_files_empty_database_shows_page_one_of_one(tmp_path: Path) -> None:
    # 0 rows: page 1 of 1 with an empty-state message and NO redirect (pages
    # floors at 1, so page=1 is in range and must not loop).
    c = client(tmp_path)
    resp = c.get("/files", follow_redirects=False)
    assert resp.status_code == 200
    assert "page 1 of 1" in resp.text
    assert resp.text.count("data-file-id=") == 0
    assert "no files" in resp.text.lower()


def test_root_redirects_to_files(tmp_path: Path) -> None:
    c = client(tmp_path, n=1)
    resp = c.get("/", follow_redirects=False)
    assert resp.status_code in (301, 302, 307, 308)
    assert resp.headers["location"].startswith("/files")


def test_files_escapes_html_in_tag_values(tmp_path: Path) -> None:
    payload = "<script>alert(1)</script>"
    c = client(tmp_path, n=1, titles={0: payload})
    resp = c.get("/files")
    assert resp.status_code == 200
    # Autoescape on: the raw markup never reaches the response...
    assert payload not in resp.text
    # ...but its escaped form does, so the value is still shown.
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text


def test_files_empty_tag_cells_render_em_dash(tmp_path: Path) -> None:
    # A fresh scan leaves artist/album/title NULL, so empty cells must show an
    # em dash. With autoescape on, writing ``"&mdash;"`` as a fallback escapes
    # it to ``&amp;mdash;`` and the browser shows the literal text ``&mdash;``.
    # The fix must render a real em dash (the character or the entity as markup)
    # and never the double-escaped form.
    c = client(tmp_path, n=1)
    resp = c.get("/files")
    assert resp.status_code == 200
    text = resp.text
    # The double-escaped garbage must never reach the page.
    assert "&amp;mdash;" not in text
    # An em dash must be present, whether as the character or as the entity
    # emitted from outside the escaped expression.
    assert "—" in text or "&mdash;" in text


def test_files_page_and_count_share_one_read_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The rows and the total must come from one read transaction: with two
    # autocommit SELECTs, a scan committing between them makes "N files /
    # page X of Y" disagree with the rows shown. Spy on the connection's
    # ``in_transaction`` flag at the moment each read starts.
    c = client(tmp_path, n=150)
    seen: list[bool] = []
    real_page, real_count = FilesRepo.page, FilesRepo.count

    def spy_page(self: FilesRepo, offset: int, limit: int) -> list[FileRow]:
        seen.append(self._conn.in_transaction)
        return real_page(self, offset, limit)

    def spy_count(self: FilesRepo) -> int:
        seen.append(self._conn.in_transaction)
        return real_count(self)

    monkeypatch.setattr(FilesRepo, "page", spy_page)
    monkeypatch.setattr(FilesRepo, "count", spy_count)
    resp = c.get("/files?page=2")
    assert resp.status_code == 200
    # Both SELECTs must start while a read transaction is open, i.e. they
    # share one snapshot instead of running as two autocommit reads.
    assert seen == [True, True]

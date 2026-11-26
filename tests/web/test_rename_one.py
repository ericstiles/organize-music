"""Tests for renaming one file from the UI (issue b8p.30, PLAN §6.4/§9.4).

The web layer's end-to-end mutation, written test-first:

* ``GET /files/{file_id}/rename`` shows a form with the current filename.
* ``POST /files/{file_id}/rename`` validates the hand-typed ``new_name`` with
  ``paths.validate_relative`` (joined under the row's folder, filename only)
  and stores a draft batch with one planned move op in ``state_dir/drafts.db``
  -- a scratch database the web process owns; nothing on disk changes.
* ``POST /batches/{batch_id}/confirm`` re-checks the row's ``row_version``
  against the draft's precondition (409 PREVIEW_STALE on mismatch), copies the
  batch and its op into ``library.db`` in one transaction, runs ``run_move``
  synchronously and renders the result.
* While ``config.mutations_enabled`` is false the confirm refuses with 403
  MUTATIONS_DISABLED; the preview still works (PLAN §9.4).
"""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from organize_music.config import load_config
from organize_music.db import migrate
from organize_music.db.files_repo import FilesRepo
from organize_music.models import FileRecord
from organize_music.ops import move
from organize_music.web import rename_confirm
from organize_music.web.app import create_app

NOW = "2026-01-01T00:00:00Z"
CONTENT = b"\x00track-one-audio-bytes\x00"
REL = "artist/album/001-Song_1.mp3"


def _open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class Env:
    """A real library root with one file, a migrated library.db, a web client."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        mutations_enabled: bool = True,
        rel: str = REL,
        content: bytes = CONTENT,
    ) -> None:
        self.root = tmp_path / "library"
        self.state = tmp_path / "state"
        self.work = tmp_path / "work"
        self.purge = tmp_path / "purge"
        self.state.mkdir()
        self.db = self.state / "library.db"
        src = self.root / rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(content)
        st = src.stat()
        conn = _open_conn(self.db)
        migrate(conn, self.db, self.state / "backups", NOW)
        self.file_id = FilesRepo(conn).insert_scanned(
            FileRecord(path=Path(rel), size=st.st_size, mtime_ns=st.st_mtime_ns, ext="mp3"),
            "audio",
            NOW,
        )
        conn.commit()
        conn.close()
        overrides = {
            "library": self.root,
            "library_mount": self.root,
            "state_dir": self.state,
            "work_dir": self.work,
            "purge_dir": self.purge,
            "mutations_enabled": mutations_enabled,
        }
        self.client = TestClient(create_app(load_config(None, overrides=overrides)))

    # -- request helpers ----------------------------------------------------

    def preview(self, new_name: str) -> TestClient.Response:
        return self.client.post(f"/files/{self.file_id}/rename", data={"new_name": new_name})

    def confirm(self) -> TestClient.Response:
        return self.client.post(f"/batches/{self.draft_batch_id()}/confirm")

    # -- database helpers ----------------------------------------------------

    def draft_batch_id(self) -> int:
        conn = _open_conn(self.state / "drafts.db")
        row = conn.execute("SELECT batch_id FROM batches ORDER BY batch_id DESC LIMIT 1").fetchone()
        conn.close()
        return int(row["batch_id"])

    def library_row(self) -> sqlite3.Row:
        conn = _open_conn(self.db)
        row = conn.execute(
            "SELECT path, path_key, row_version, status FROM files WHERE file_id = ?",
            (self.file_id,),
        ).fetchone()
        conn.close()
        return row

    def library_batches(self) -> list[sqlite3.Row]:
        conn = _open_conn(self.db)
        rows = conn.execute("SELECT * FROM batches ORDER BY batch_id").fetchall()
        conn.close()
        return rows


def test_rename_form_shows_current_filename(tmp_path: Path) -> None:
    env = Env(tmp_path)
    resp = env.client.get(f"/files/{env.file_id}/rename")
    assert resp.status_code == 200
    # The form is pre-filled with the file's current name.
    assert "001-Song_1.mp3" in resp.text
    assert 'name="new_name"' in resp.text


def test_rename_form_404_for_missing_file(tmp_path: Path) -> None:
    env = Env(tmp_path)
    assert env.client.get("/files/999/rename").status_code == 404


def test_preview_creates_a_draft_and_changes_nothing(tmp_path: Path) -> None:
    env = Env(tmp_path)
    resp = env.preview("001-Renamed.mp3")
    assert resp.status_code == 200
    # The preview offers a confirm, and nothing on disk has changed.
    assert "/confirm" in resp.text
    assert (env.root / REL).read_bytes() == CONTENT
    assert not (env.root / "artist/album/001-Renamed.mp3").exists()
    # The draft lives in the scratch drafts.db, not in library.db.
    dconn = _open_conn(env.state / "drafts.db")
    batch = dconn.execute("SELECT * FROM batches WHERE kind = 'rename'").fetchone()
    op = dconn.execute("SELECT * FROM operations ORDER BY op_id").fetchone()
    dconn.close()
    assert batch is not None
    assert batch["state"] == "draft"
    assert op["state"] == "planned"
    assert op["file_id"] == env.file_id
    assert op["expect_path"] == REL
    assert int(op["expect_size"]) == len(CONTENT)
    assert int(op["expect_row_version"]) == 1
    params = json.loads(op["params_json"])
    assert params["dst"] == "artist/album/001-Renamed.mp3"
    # library.db is untouched: no batches, no operations, row_version still 1.
    conn = _open_conn(env.db)
    assert conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 0
    assert int(conn.execute("SELECT row_version FROM files").fetchone()[0]) == 1
    conn.close()


def test_confirm_renames_the_file_and_updates_the_row(tmp_path: Path) -> None:
    env = Env(tmp_path)
    assert env.preview("001-Renamed.mp3").status_code == 200
    resp = env.confirm()
    assert resp.status_code == 200
    # Disk: the file was renamed.
    assert (env.root / "artist/album/001-Renamed.mp3").read_bytes() == CONTENT
    assert not (env.root / REL).exists()
    # Row: path updated, row_version bumped by one.
    row = env.library_row()
    assert row["path"] == "artist/album/001-Renamed.mp3"
    assert int(row["row_version"]) == 2
    # The batch in library.db completed with one success.
    (batch,) = env.library_batches()
    assert batch["state"] == "completed"
    assert batch["succeeded"] == 1 and batch["failed"] == 0
    assert "001-Renamed.mp3" in resp.text


def test_confirm_after_the_row_changed_is_409_preview_stale(tmp_path: Path) -> None:
    env = Env(tmp_path)
    assert env.preview("001-Renamed.mp3").status_code == 200
    # Simulate an external change (a scan) between preview and confirm.
    conn = _open_conn(env.db)
    conn.execute(
        "UPDATE files SET size = size + 5, row_version = row_version + 1 WHERE file_id = ?",
        (env.file_id,),
    )
    conn.commit()
    conn.close()
    resp = env.confirm()
    assert resp.status_code == 409
    assert "PREVIEW_STALE" in resp.text
    # Nothing moved; the row carries only the simulated change.
    assert (env.root / REL).read_bytes() == CONTENT
    assert int(env.library_row()["row_version"]) == 2


def test_new_name_with_path_traversal_is_422(tmp_path: Path) -> None:
    env = Env(tmp_path)
    resp = env.preview("../x.mp3")
    assert resp.status_code == 422
    # No draft was stored and nothing moved.
    db = env.state / "drafts.db"
    if db.is_file():
        conn = _open_conn(db)
        assert conn.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0
        conn.close()
    assert (env.root / REL).read_bytes() == CONTENT


def test_new_name_with_a_folder_is_422(tmp_path: Path) -> None:
    # Filename only, same folder: a '/' in the typed name would be a move to
    # another folder, which is out of scope for this tracer.
    env = Env(tmp_path)
    assert env.preview("other/x.mp3").status_code == 422


def test_confirm_with_mutations_disabled_is_403(tmp_path: Path) -> None:
    env = Env(tmp_path, mutations_enabled=False)
    # PLAN §9.4: with mutations off the preview still works...
    assert env.preview("001-Renamed.mp3").status_code == 200
    # ...but the confirm refuses with 403 MUTATIONS_DISABLED.
    resp = env.confirm()
    assert resp.status_code == 403
    assert "MUTATIONS_DISABLED" in resp.text
    # Nothing moved and nothing was written to library.db.
    assert (env.root / REL).read_bytes() == CONTENT
    assert int(env.library_row()["row_version"]) == 1
    assert env.library_batches() == []


def test_confirm_collision_shows_the_error_and_moves_nothing(tmp_path: Path) -> None:
    env = Env(tmp_path)
    (env.root / "artist/album/001-Renamed.mp3").write_bytes(b"someone-elses-bytes")
    assert env.preview("001-Renamed.mp3").status_code == 200
    resp = env.confirm()
    assert resp.status_code == 200
    assert "COLLISION" in resp.text
    # Both files are exactly as they were; the row is untouched.
    assert (env.root / REL).read_bytes() == CONTENT
    assert (env.root / "artist/album/001-Renamed.mp3").read_bytes() == b"someone-elses-bytes"
    assert int(env.library_row()["row_version"]) == 1
    (batch,) = env.library_batches()
    assert batch["state"] == "completed_with_errors"
    assert batch["failed"] == 1


def test_case_only_rename_commits(tmp_path: Path) -> None:
    env = Env(tmp_path, rel="a/one.mp3", content=b"case-only-bytes")
    assert env.preview("One.mp3").status_code == 200
    resp = env.confirm()
    assert resp.status_code == 200
    # Assert on the exact directory listing (the real, case-preserving names),
    # so the test also holds on case-insensitive filesystems.
    assert os.listdir(env.root / "a") == ["One.mp3"]
    row = env.library_row()
    assert row["path"] == "a/One.mp3"
    assert int(row["row_version"]) == 2


def test_confirm_missing_batch_is_404(tmp_path: Path) -> None:
    env = Env(tmp_path)
    resp = env.client.post("/batches/999/confirm")
    assert resp.status_code == 404


def test_case_only_rename_with_a_dot(tmp_path: Path) -> None:
    """'ONE' vs 'one' differ, so the embedded dot is not a suffix (PLAN §6.2):
    the op takes the via-temp route and commits a real case rename."""
    env = Env(tmp_path, rel="a/ONE.mp3")
    assert env.preview("one.mp3").status_code == 200
    resp = env.confirm()
    assert resp.status_code == 200
    # Exactly one file remains, at the requested name (works on case-
    # insensitive filesystems too: a different-case rename is a real rename).
    assert os.listdir(env.root / "a") == ["one.mp3"]
    row = env.library_row()
    assert row["path"] == "a/one.mp3"
    assert int(row["row_version"]) == 2


def test_confirmation_is_one_shot(tmp_path: Path) -> None:
    """Confirming a draft consumes it: a second confirm gets 404 (not a re-copy).

    The draft is deleted before the op is copied into library.db, so a crash
    in between loses the draft but changes nothing -- the user re-previews.
    """
    env = Env(tmp_path)
    assert env.preview("001-Renamed.mp3").status_code == 200
    batch_id = env.draft_batch_id()
    first = env.client.post(f"/batches/{batch_id}/confirm")
    assert first.status_code == 200
    second = env.client.post(f"/batches/{batch_id}/confirm")
    assert second.status_code == 404
    # Exactly one op was ever copied into library.db.
    conn = _open_conn(env.db)
    assert conn.execute("SELECT COUNT(*) FROM operations").fetchone()[0] == 1
    conn.close()


def test_confirm_when_run_move_raises_mid_move(tmp_path: Path) -> None:
    """A raised step (e.g. disk full) leaves the op where it stopped: the page
    says it will be recovered at the next startup, and the op stays active
    (``applied`` here: the file moved, the row was not committed) so
    ``startup_recovery`` can finish it."""
    env = Env(tmp_path)
    assert env.preview("001-Renamed.mp3").status_code == 200
    draft_batch_id = env.draft_batch_id()
    real_run_move = rename_confirm.run_move

    def boom(op, ctx):
        # The two real steps of a non-case-only move: planned -> intent ->
        # applied (the rename happens in ``_intent``). Then an error before
        # the journal/commit step.
        op = ctx.oplog.get(op.op_id)
        op = move._step(op, ctx)
        move._step(op, ctx)
        raise OSError("disk full while writing the journal")

    rename_confirm.run_move = boom
    try:
        resp = env.client.post(f"/batches/{draft_batch_id}/confirm")
    finally:
        rename_confirm.run_move = real_run_move
    assert resp.status_code == 200
    assert "recovered" in resp.text
    # Disk: the file moved to the new name. Row: not yet committed.
    assert (env.root / "artist/album/001-Renamed.mp3").exists()
    row = env.library_row()
    assert row["path"] == REL
    assert int(row["row_version"]) == 1
    # Op left active; the draft is gone (consumed before the copy).
    conn = _open_conn(env.db)
    (op,) = conn.execute("SELECT state FROM operations").fetchall()
    conn.close()
    assert op["state"] == "applied"
    dconn = _open_conn(env.state / "drafts.db")
    assert dconn.execute("SELECT COUNT(*) FROM batches").fetchone()[0] == 0
    dconn.close()


def test_confirm_when_run_move_raises_before_any_step(tmp_path: Path) -> None:
    """A failure before any step ran: the op is left ``planned`` and the page
    says it will be recovered at the next startup (recovery re-runs run_move,
    which then does the prechecks fresh)."""
    env = Env(tmp_path)
    assert env.preview("001-Renamed.mp3").status_code == 200
    draft_batch_id = env.draft_batch_id()
    real_run_move = rename_confirm.run_move

    def boom(op, ctx):
        raise OSError("library root vanished")

    rename_confirm.run_move = boom
    try:
        resp = env.client.post(f"/batches/{draft_batch_id}/confirm")
    finally:
        rename_confirm.run_move = real_run_move
    assert resp.status_code == 200
    assert "recovered" in resp.text
    # Nothing moved on disk, and the op is still planned.
    assert (env.root / REL).read_bytes() == CONTENT
    assert not (env.root / "artist/album/001-Renamed.mp3").exists()
    conn = _open_conn(env.db)
    (op,) = conn.execute("SELECT state FROM operations").fetchall()
    conn.close()
    assert op["state"] == "planned"

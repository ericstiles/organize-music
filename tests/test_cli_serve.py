"""CLI tests for the ``serve`` and ``recover`` commands (issue b8p.32, PLAN §6.4).

``recover`` takes the single-writer lock, migrates, runs the startup recovery
and exits 0 (1 when any op needs attention); a lock already held by a running
server exits 2 with "server is running", and a not-mounted library exits 1
because nothing could be verified (PLAN §6.4: recovery waits with
LIBRARY_NOT_MOUNTED).

``serve`` takes the same lock (held for the server's lifetime, PLAN §6.4
"One writer"), migrates, recovers when the library is mounted, and hands
``create_app(config)`` to ``uvicorn.run`` with the config's bind host and
port and exactly one worker. With the library not mounted it still serves,
read-only.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest
import uvicorn

from organize_music import cli
from organize_music.db import WriterLock, migrate
from organize_music.db.files_repo import FilesRepo
from organize_music.models import FileRecord
from organize_music.ops.move import plan_move_params
from organize_music.ops.oplog_repo import OplogRepo

NOW = "2026-04-01T00:00:00Z"
REL = "a/one.mp3"
CONTENT = b"track-one-bytes"


def _open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class ServeEnv:
    """One file under the library root, a migrated state DB, a config.yaml."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "library"
        self.state = tmp_path / "state"
        self.work = tmp_path / "work"
        self.purge = tmp_path / "purge"
        self.state.mkdir()
        src = self.root / REL
        src.parent.mkdir(parents=True)
        src.write_bytes(CONTENT)
        self.file_stat = src.stat()
        self.db = self.state / "library.db"
        conn = _open_conn(self.db)
        migrate(conn, self.db, self.state / "backups", NOW)
        self.file_id = FilesRepo(conn).insert_scanned(
            FileRecord(
                path=Path(REL),
                size=self.file_stat.st_size,
                mtime_ns=self.file_stat.st_mtime_ns,
                ext="mp3",
            ),
            "audio",
            NOW,
        )
        self._oplog = OplogRepo(conn, mirror=lambda record: None, clock=lambda: NOW)
        conn.commit()
        conn.close()
        self.config = tmp_path / "config.yaml"
        self.config.write_text(
            f"library: {self.root}\n"
            f"library_mount: {self.root}\n"
            f"state_dir: {self.state}\n"
            f"work_dir: {self.work}\n"
            f"purge_dir: {self.purge}\n"
            "bind_host: 127.0.0.1\n"
            "bind_port: 8765\n"
            "mutations_enabled: true\n",
            encoding="utf-8",
        )

    def add_op(self, kind: str = "move", dst: str = "a/renamed.mp3", state: str = "planned") -> int:
        """A batch and one op over the env's file; ``state`` unless planned."""
        conn = _open_conn(self.db)
        try:
            oplog = OplogRepo(conn, mirror=lambda record: None, clock=lambda: NOW)
            op_id = oplog.add_op(
                oplog.create_batch({"move": "rename", "retag": "edit"}[kind], kind, "{}"),
                self.file_id,
                unit_seq=0,
                step_seq=0,
                kind=kind,
                expect=(REL, self.file_stat.st_size, self.file_stat.st_mtime_ns, 1),
                # Neither of the env's ops is a case-only rename, so the
                # op_id hint (only used to build a case-only ``via``) is inert.
                params=plan_move_params(REL, dst, op_id_hint="1"),
            )
            if state != "planned":
                conn.execute("UPDATE operations SET state = ? WHERE op_id = ?", (state, op_id))
            conn.commit()
        finally:
            conn.close()
        return op_id

    def op_row(self, op_id: int) -> sqlite3.Row:
        conn = _open_conn(self.db)
        try:
            return conn.execute("SELECT * FROM operations WHERE op_id = ?", (op_id,)).fetchone()
        finally:
            conn.close()

    def file_row(self) -> sqlite3.Row:
        conn = _open_conn(self.db)
        try:
            return conn.execute("SELECT * FROM files WHERE file_id = ?", (self.file_id,)).fetchone()
        finally:
            conn.close()

    def run(self, *argv: str) -> int:
        return cli.main([*argv, "--config", str(self.config)])

    def fake_mounted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Simulate the drive being mounted: ismount true for the library only."""
        monkeypatch.setattr("os.path.ismount", lambda path: str(path) == str(self.root))

    def hold_lock(self) -> WriterLock:
        """Acquire the writer lock (as a running server would) and keep it."""
        lock = WriterLock(self.state / "writer.lock")
        lock.__enter__()
        return lock

    def unlock(self, lock: WriterLock) -> None:
        lock.__exit__(None, None, None)

    def serve_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> list[tuple[object, dict[str, object]]]:
        """Patch uvicorn.run and record its (app, kwargs) calls."""
        calls: list[tuple[object, dict[str, object]]] = []

        def fake_run(app: object, **kwargs: object) -> None:
            calls.append((app, kwargs))

        monkeypatch.setattr(uvicorn, "run", fake_run)
        return calls


def test_recover_held_lock_exits_2_server_running(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = ServeEnv(tmp_path)
    lock = env.hold_lock()
    try:
        code = env.run("recover")
    finally:
        env.unlock(lock)
    err = capsys.readouterr().err
    assert code == 2
    assert "server is running" in err


def test_serve_held_lock_exits_2_and_starts_nothing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = ServeEnv(tmp_path)
    calls = env.serve_calls(monkeypatch)
    lock = env.hold_lock()
    try:
        code = env.run("serve")
    finally:
        env.unlock(lock)
    err = capsys.readouterr().err
    assert code == 2
    assert "server is running" in err
    assert calls == []  # the app never reached uvicorn


def test_recover_commits_interrupted_move_and_prints_count(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = ServeEnv(tmp_path)
    op_id = env.add_op("move", "a/renamed.mp3", state="applied")
    (env.root / REL).unlink()
    dst = env.root / "a/renamed.mp3"
    dst.write_bytes(CONTENT)
    os.utime(dst, ns=(env.file_stat.st_mtime_ns, env.file_stat.st_mtime_ns))
    env.fake_mounted(monkeypatch)

    code = env.run("recover")

    assert code == 0
    err = capsys.readouterr().err
    assert "committed 1" in err
    assert env.op_row(op_id)["state"] == "committed"
    row = env.file_row()
    assert row["path"] == "a/renamed.mp3"
    assert int(row["row_version"]) == 2
    # A second pass over the recovered library is a no-op.
    capsys.readouterr()
    assert env.run("recover") == 0
    assert "committed 0" in capsys.readouterr().err


def test_recover_needs_attention_exits_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env = ServeEnv(tmp_path)
    op_id = env.add_op("retag", "a/one.mp3", state="applied")
    env.fake_mounted(monkeypatch)

    code = env.run("recover")

    assert code == 1
    assert "needs attention" in capsys.readouterr().err
    row = env.op_row(op_id)
    assert row["state"] == "needs_attention"
    assert row["error_code"] == "NEEDS_ATTENTION"


def test_recover_unmounted_library_skips_recovery(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    env = ServeEnv(tmp_path)
    op_id = env.add_op("move", "a/renamed.mp3", state="applied")
    # No monkeypatch: a tmp directory is not a mount point.

    code = env.run("recover")

    err = capsys.readouterr().err
    assert code == 1
    assert "LIBRARY_NOT_MOUNTED" in err
    # Nothing recovered and no report printed as if it had.
    assert env.op_row(op_id)["state"] == "applied"
    assert "committed" not in err


def test_recover_no_active_ops_exits_0(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    env = ServeEnv(tmp_path)
    env.fake_mounted(monkeypatch)

    assert env.run("recover") == 0
    assert "committed 0" in capsys.readouterr().err


def test_serve_receives_config_bind_host_port_and_one_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = ServeEnv(tmp_path)
    env.fake_mounted(monkeypatch)
    calls = env.serve_calls(monkeypatch)

    code = env.run("serve")

    assert code == 0
    assert len(calls) == 1
    app, kwargs = calls[0]
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8765
    assert kwargs["workers"] == 1
    # The app is the real factory output over the configured database.
    assert app.state.db_path == env.db


def test_serve_unmounted_library_still_serves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env = ServeEnv(tmp_path)
    op_id = env.add_op("move", "a/renamed.mp3", state="applied")
    calls = env.serve_calls(monkeypatch)
    # No monkeypatch: the library is not mounted.

    code = env.run("serve")

    assert code == 0
    assert len(calls) == 1  # read-only, but it serves
    assert env.op_row(op_id)["state"] == "applied"  # recovery did not run

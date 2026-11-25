"""Tests for the startup recovery dispatcher (PLAN §6.4, catalogue P1-15).

At startup, before the worker accepts work, every operation in an ACTIVE
state must be driven to a terminal one.  ``recover_all`` walks
``oplog.active_ops()`` and dispatches by kind: a ``move`` goes through
``recover_move``; any kind without a registered recovery (today:
``retag`` -- its recovery is registered in phase 5) stops for a human in
``needs_attention``.  The ``RecoveryReport`` counts the ``committed`` and
``failed`` outcomes and lists the op ids a human must look at; a second
pass over a fully recovered library is a no-op.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

import pytest
from support.invariants import assert_consistent

from organize_music.db import migrate
from organize_music.fsops.protocol import RealFs
from organize_music.ops.context import OpContext
from organize_music.ops.move import plan_move_params
from organize_music.ops.oplog_repo import OplogRepo
from organize_music.ops.recover import RecoveryReport, recover_all
from organize_music.paths import path_key

NOW = "2026-03-01T00:00:00Z"

# Every column the 0001 schema requires for a present audio row.
_INSERT = (
    "INSERT INTO files "
    "(path, path_key, last_path, status, kind, size, mtime_ns, ext, "
    "artist, artist_src, album_artist, album_artist_src, album, album_src, "
    "title, title_src, track_number, track_number_src, disc_number, "
    "disc_number_src, year, year_src, genre, genre_src, row_version, "
    "first_seen_at, updated_at) "
    "VALUES (?, ?, ?, 'present', 'audio', ?, ?, ?, "
    "'a', 'tag', 'a', 'tag', 'a', 'tag', 't', 'tag', '1', 'tag', '1', 'tag', "
    "'2001', 'tag', 'Rock', 'tag', 1, ?, ?)"
)


def _open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


class Lib:
    """One on-disk library, a migrated DB, and any number of files and ops."""

    def __init__(self, base: Path) -> None:
        self.root = base / "root"
        self.work_dir = base / "work"
        self.purge_dir = base / "purge"
        db_dir = self.work_dir / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "library.db"
        self.conn = _open_conn(db_path)
        migrate(self.conn, db_path, db_dir / "backups", NOW)
        self.root.mkdir(parents=True, exist_ok=True)
        self.records: list[dict[str, object]] = []
        self.files: dict[str, tuple[int, int, int]] = {}  # rel -> (file_id, size, mtime_ns)
        self.ops: list[int] = []

    @property
    def op_ids(self) -> tuple[int, ...]:
        return tuple(self.ops)

    def repo(self) -> OplogRepo:
        return OplogRepo(self.conn, mirror=self.records.append, clock=lambda: NOW)

    def ctx(self, fs: RealFs) -> OpContext:
        return OpContext(
            root=self.root,
            work_dir=self.work_dir,
            purge_dir=self.purge_dir,
            fs=fs,
            oplog=self.repo(),
            conn=self.conn,
            clock=lambda: NOW,
        )

    def add_file(self, rel: str, content: bytes) -> int:
        """A new on-disk file plus its ``files`` row; returns the file id."""
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        st = path.stat()
        fid = int(
            self.conn.execute(
                _INSERT,
                (rel, path_key(rel), rel, st.st_size, st.st_mtime_ns, "mp3", NOW, NOW),
            ).lastrowid
        )
        self.conn.commit()
        self.files[rel] = (fid, st.st_size, st.st_mtime_ns)
        return fid

    def write_file(self, rel: str, content: bytes, mtime_ns: int | None = None) -> None:
        """Rewrite an existing path, optionally restoring its original mtime."""
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if mtime_ns is not None:
            os.utime(path, ns=(mtime_ns, mtime_ns))

    def add_op(self, rel: str, dst_rel: str, kind: str = "move", unit_seq: int = 0) -> int:
        """A planned op for the ``files`` row added for ``rel``."""
        fid, size, mtime_ns = self.files[rel]
        batch_kind = {"move": "rename", "retag": "edit"}[kind]
        op_id = self.repo().add_op(
            self.repo().create_batch(batch_kind, kind, "{}"),
            fid,
            unit_seq=unit_seq,
            step_seq=0,
            kind=kind,
            expect=(rel, size, mtime_ns, 1),
            params=plan_move_params(rel, dst_rel, op_id_hint=str(1)),
        )
        self.ops.append(op_id)
        return op_id

    def fix_via(self, op_id: int) -> None:
        """Point the op's ``via`` name at its real op id (case-only renames)."""
        op = self.repo().get(op_id)
        params = dict(op.params)
        if params.get("via") is not None:
            folder = op.expect_path.rsplit("/", 1)[0]
            params["via"] = f"{folder}/.om-{op_id}.tmp" if folder else f".om-{op_id}.tmp"
            self.set_op(op_id, op.state, params)

    def set_op(self, op_id: int, state: str, params: dict[str, object] | None = None) -> None:
        sql = "UPDATE operations SET state = ?"
        values: list[object] = [state]
        if params is not None:
            sql += ", params_json = ?"
            values.append(json.dumps(params))
        sql += " WHERE op_id = ?"
        self.conn.execute(sql, (*values, op_id))
        self.conn.commit()

    def state_of(self, op_id: int) -> str:
        row = self.conn.execute("SELECT state FROM operations WHERE op_id = ?", (op_id,)).fetchone()
        return row[0]

    def row_of(self, file_id: int) -> tuple[str, int, str]:
        r = self.conn.execute(
            "SELECT path, row_version, status FROM files WHERE file_id = ?", (file_id,)
        ).fetchone()
        return (r["path"], int(r["row_version"]), r["status"])

    def op_row(self, op_id: int) -> tuple[str, str | None, str | None]:
        r = self.conn.execute(
            "SELECT state, error_code, error_detail FROM operations WHERE op_id = ?",
            (op_id,),
        ).fetchone()
        return (r["state"], r["error_code"], r["error_detail"])

    def snapshot(self) -> list[tuple[str, int, int]]:
        """(rel path, size, mtime_ns) of every file under root, sorted."""
        out: list[tuple[str, int, int]] = []
        for directory, _dirs, files in os.walk(self.root):
            for name in files:
                p = Path(directory) / name
                st = p.stat()
                out.append((str(p.relative_to(self.root)), st.st_size, st.st_mtime_ns))
        out.sort()
        return out


def build_mixed(tmp_path: Path) -> Lib:
    """Three active moves, one per §6.2 disk picture.

    A: V only, a case-only rename interrupted after its first rename
    (row 2; recovers to ``committed``).  B: D only, the rename finished but
    never committed (row 3; recovers to ``committed``).  C: S only, the
    rename never happened and one folder was created (row 1; recovers to
    ``failed``).
    """
    lib = Lib(tmp_path)
    lib.add_file("a/one.mp3", b"case-bytes")
    op_a = lib.add_op("a/one.mp3", "a/One.mp3")
    lib.fix_via(op_a)
    (lib.root / "a/one.mp3").unlink()
    via = f"a/.om-{op_a}.tmp"
    lib.write_file(via, b"case-bytes", mtime_ns=lib.files["a/one.mp3"][2])
    lib.set_op(op_a, "intent")

    lib.add_file("b/two.mp3", b"two-bytes")
    op_b = lib.add_op("b/two.mp3", "b/deep/two.mp3")
    (lib.root / "b/two.mp3").unlink()
    lib.write_file("b/deep/two.mp3", b"two-bytes", mtime_ns=lib.files["b/two.mp3"][2])
    lib.set_op(op_b, "applied")

    lib.add_file("c/three.mp3", b"three-bytes")
    op_c = lib.add_op("c/three.mp3", "c/new/three.mp3")
    (lib.root / "c/new").mkdir(parents=True, exist_ok=True)
    params = dict(lib.repo().get(op_c).params)
    params["created_dirs"] = ["c/new"]
    lib.set_op(op_c, "intent", params)
    return lib


def test_three_active_moves_mixed_disk_states(tmp_path: Path) -> None:
    lib = build_mixed(tmp_path)
    op_a, op_b, op_c = lib.op_ids

    report = recover_all(lib.ctx(RealFs()))
    assert report == RecoveryReport(committed=2, failed=1, needs_attention=())
    assert lib.state_of(op_a) == "committed"
    assert lib.state_of(op_b) == "committed"
    assert lib.state_of(op_c) == "failed"
    assert lib.op_row(op_c) == ("failed", "INTERRUPTED", "rename did not persist")

    # No active op remains; every files row follows its content.
    assert lib.ctx(RealFs()).oplog.active_ops() == []
    assert lib.row_of(lib.files["a/one.mp3"][0]) == ("a/One.mp3", 2, "present")
    assert lib.row_of(lib.files["b/two.mp3"][0]) == ("b/deep/two.mp3", 2, "present")
    assert lib.row_of(lib.files["c/three.mp3"][0]) == ("c/three.mp3", 1, "present")
    # C's file is untouched at the source; the emptied created folder is gone.
    assert (lib.root / "c/three.mp3").read_bytes() == b"three-bytes"
    assert not (lib.root / "c/new").exists()
    original = Counter(
        {hashlib.sha256(b).hexdigest(): 1 for b in (b"case-bytes", b"two-bytes", b"three-bytes")}
    )
    assert_consistent(lib.root, lib.conn, extra_dirs=(lib.work_dir,), original=original)

    # A second pass over the fully recovered library is a no-op.
    n = len(lib.records)
    snap = lib.snapshot()
    again = recover_all(lib.ctx(RealFs()))
    assert again == RecoveryReport(committed=0, failed=0, needs_attention=())
    assert len(lib.records) == n
    assert lib.snapshot() == snap


def test_no_ops_report_is_zero(tmp_path: Path) -> None:
    lib = Lib(tmp_path)
    report = recover_all(lib.ctx(RealFs()))
    assert report == RecoveryReport(committed=0, failed=0, needs_attention=())


def test_planned_ops_are_untouched_and_report_is_zero(tmp_path: Path) -> None:
    lib = Lib(tmp_path)
    lib.add_file("a/one.mp3", b"planned-bytes")
    op_a = lib.add_op("a/one.mp3", "a/new/one.mp3")
    assert lib.state_of(op_a) == "planned"

    report = recover_all(lib.ctx(RealFs()))
    assert report == RecoveryReport(committed=0, failed=0, needs_attention=())
    assert lib.state_of(op_a) == "planned"  # 'planned' is not an active state


@pytest.mark.parametrize("state", ["intent", "staged", "parked", "applied"])
def test_unknown_kind_goes_to_needs_attention(tmp_path: Path, state: str) -> None:
    lib = Lib(tmp_path)
    lib.add_file("a/one.mp3", b"retag-bytes")
    op_move = lib.add_op("a/one.mp3", "a/new/one.mp3")  # stays planned: not active
    op_retag = lib.add_op("a/one.mp3", "a/one.mp3", kind="retag", unit_seq=1)
    lib.set_op(op_retag, state)

    report = recover_all(lib.ctx(RealFs()))
    assert report.committed == 0
    assert report.failed == 0
    assert report.needs_attention == (op_retag,)
    row = lib.op_row(op_retag)
    assert row[0] == "needs_attention"
    assert row[1] == "NEEDS_ATTENTION"
    assert "retag" in (row[2] or "")
    assert lib.state_of(op_move) == "planned"  # the planned move is untouched


def test_unexpected_terminal_outcome_fails_loudly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import organize_music.ops.recover as recover_mod

    lib = Lib(tmp_path)
    lib.add_file("a/one.mp3", b"bytes")
    op_a = lib.add_op("a/one.mp3", "a/new/one.mp3")
    (lib.root / "a/one.mp3").unlink()
    (lib.root / "a/new").mkdir(parents=True, exist_ok=True)
    lib.set_op(op_a, "intent")
    monkeypatch.setattr(
        recover_mod,
        "recover_move",
        lambda op, ctx: dataclasses.replace(op, state="skipped"),
    )
    with pytest.raises(RuntimeError, match="skipped"):
        recover_all(lib.ctx(RealFs()))

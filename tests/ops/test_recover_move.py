"""Tests for move recovery (PLAN §6.2 recovery table, issue b8p.24 / catalogue P1-14).

After a crash, every non-terminal move must be finished or undone safely:
``recover_move`` applies the §6.2 recovery table row by row, where S, V and D
mean that an entry exists at the op's src, via and dst names (checked with
``entry_exists`` on the exact names).  Whenever two of the three names exist at
once -- the exFAT doubled-entry danger -- recovery never removes either name
and stops for a human with ``needs_attention``.  The extended crash matrix
re-runs the P1-13 matrix through recovery: after each injected crash the op
must be terminal and the library consistent, and a second recover call must be
a no-op.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import Counter
from pathlib import Path

import pytest
from support.faulty_fs import FaultyFs, SimulatedCrash, count_calls
from support.invariants import assert_consistent

from organize_music.db import migrate
from organize_music.fsops.protocol import RealFs
from organize_music.ops.context import OpContext
from organize_music.ops.move import plan_move_params, run_move
from organize_music.ops.oplog_repo import OplogRepo
from organize_music.ops.recover_move import recover_move
from organize_music.paths import path_key

NOW = "2026-03-01T00:00:00Z"


# --------------------------------------------------------------------------- #
# environment helpers
# --------------------------------------------------------------------------- #


def _open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _migrated(db_dir: Path) -> sqlite3.Connection:
    path = db_dir / "library.db"
    conn = _open_conn(path)
    migrate(conn, path, db_dir / "backups", NOW)
    return conn


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


class Env:
    """One on-disk library plus a migrated DB and a move op, in any state."""

    def __init__(
        self,
        root: Path,
        work_dir: Path,
        purge_dir: Path,
        src_rel: str,
        dst_rel: str,
        content: bytes,
    ) -> None:
        self.root = root
        self.work_dir = work_dir
        self.purge_dir = purge_dir
        self.src_rel = src_rel
        self.dst_rel = dst_rel
        self.content = content
        db_dir = work_dir / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        self.conn = _migrated(db_dir)
        src = root / src_rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_bytes(content)
        st = src.stat()
        fid = self.conn.execute(
            _INSERT,
            (src_rel, path_key(src_rel), src_rel, st.st_size, st.st_mtime_ns, "mp3", NOW, NOW),
        ).lastrowid
        self.file_id = int(fid)
        self.size = st.st_size
        self.mtime_ns = st.st_mtime_ns
        self.conn.commit()
        self.records: list[dict[str, object]] = []
        repo = OplogRepo(self.conn, mirror=self.records.append, clock=lambda: NOW)
        self.op_id = repo.add_op(
            repo.create_batch("rename", "move", "{}"),
            self.file_id,
            unit_seq=0,
            step_seq=0,
            kind="move",
            expect=(src_rel, self.size, self.mtime_ns, 1),
            params=plan_move_params(src_rel, dst_rel, op_id_hint=str(1)),
        )

    def ctx(self, fs: RealFs) -> OpContext:
        oplog = OplogRepo(self.conn, mirror=self.records.append, clock=lambda: NOW)
        return OpContext(
            root=self.root,
            work_dir=self.work_dir,
            purge_dir=self.purge_dir,
            fs=fs,
            oplog=oplog,
            conn=self.conn,
            clock=lambda: NOW,
        )

    def get_op(self) -> object:
        return OplogRepo(self.conn, mirror=self.records.append, clock=lambda: NOW).get(self.op_id)

    def state(self) -> str:
        row = self.conn.execute(
            "SELECT state FROM operations WHERE op_id = ?", (self.op_id,)
        ).fetchone()
        return row[0]

    def set_op(self, state: str, params: dict[str, object] | None = None) -> None:
        """Construct the op's state (and optional params) directly, per the issue."""
        sql = "UPDATE operations SET state = ?"
        values: list[object] = [state]
        if params is not None:
            sql += ", params_json = ?"
            values.append(json.dumps(params))
        sql += " WHERE op_id = ?"
        self.conn.execute(sql, (*values, self.op_id))
        self.conn.commit()

    def params(self) -> dict[str, object]:
        row = self.conn.execute(
            "SELECT params_json FROM operations WHERE op_id = ?", (self.op_id,)
        ).fetchone()
        return json.loads(row[0])

    def via_rel(self) -> str:
        """The intermediate name the op's params carry (case-only renames)."""
        folder = self.src_rel.rsplit("/", 1)[0]
        return f"{folder}/.om-{self.op_id}.tmp"

    def file_at(self, rel: str, content: bytes, mtime_ns: int | None = None) -> Path:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        if mtime_ns is not None:
            os.utime(path, ns=(mtime_ns, mtime_ns))
        return path

    def row(self) -> tuple[str, int, str]:
        r = self.conn.execute(
            "SELECT path, row_version, status FROM files WHERE file_id = ?", (self.file_id,)
        ).fetchone()
        return (r["path"], int(r["row_version"]), r["status"])

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


def build_env(base: Path, src_rel: str, dst_rel: str, content: bytes) -> Env:
    """A fresh library, DB and planned op under ``base`` (isolated per call)."""
    root = base / "root"
    work_dir = base / "work"
    purge_dir = base / "purge"
    return Env(root, work_dir, purge_dir, src_rel, dst_rel, content)


def recover(env: Env) -> object:
    return recover_move(env.get_op(), env.ctx(RealFs()))


def params_for(env: Env, created_dirs: list[str] | None = None) -> dict[str, object]:
    p = plan_move_params(env.src_rel, env.dst_rel, op_id_hint=str(env.op_id))
    p["via"] = env.via_rel() if p["via"] is not None else None
    p["created_dirs"] = created_dirs or []
    return p


def is_case_insensitive(base: Path) -> bool:
    probe = base / "_cs_probe"
    probe.mkdir(exist_ok=True)
    (probe / "caseprobe.txt").write_text("x")
    return (probe / "CaseProbe.TXT").exists()


# --------------------------------------------------------------------------- #
# row builders: disk state + op state per §6.2 recovery row
# --------------------------------------------------------------------------- #


def build_row1(tmp_path: Path) -> Env:
    """S only: rename never happened, folders created (row 1)."""
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"audio-bytes")
    (env.root / "a/new").mkdir(parents=True, exist_ok=True)
    env.set_op("intent", params_for(env, created_dirs=["a/new"]))
    return env


def build_row2(tmp_path: Path, state: str = "intent") -> Env:
    """V only: case-only rename half done (row 2)."""
    env = build_env(tmp_path, "a/one.mp3", "a/One.mp3", b"case-bytes")
    (env.root / "a/one.mp3").unlink()
    env.file_at(env.via_rel(), b"case-bytes", mtime_ns=env.mtime_ns)
    env.set_op(state, params_for(env))
    return env


def build_row3(tmp_path: Path, state: str = "applied") -> Env:
    """D only, matching: rename done (row 3)."""
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"moved-bytes")
    (env.root / "a/one.mp3").unlink()
    env.file_at("a/new/one.mp3", b"moved-bytes", mtime_ns=env.mtime_ns)
    env.set_op(state, params_for(env))
    return env


def build_row4(tmp_path: Path) -> Env:
    """D only, mismatching: something else is at dst (row 4)."""
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"moved-bytes")
    (env.root / "a/one.mp3").unlink()
    dst = env.root / "a/new/one.mp3"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"someone-elses-bigger-bytes-data")
    env.set_op("applied", params_for(env))
    return env


def build_row5(tmp_path: Path) -> Env:
    """S and D both exist: doubled entry (row 5)."""
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"our-content")
    (env.root / "a/new/one.mp3").parent.mkdir(parents=True, exist_ok=True)
    (env.root / "a/new/one.mp3").write_bytes(b"other-content")
    env.set_op("intent", params_for(env))
    return env


def build_row6(tmp_path: Path) -> Env:
    """Nothing anywhere: file not found (row 6)."""
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"gone")
    (env.root / "a/one.mp3").unlink()
    env.set_op("applied", params_for(env))
    return env


# --------------------------------------------------------------------------- #
# recovery table, one test per row
# --------------------------------------------------------------------------- #


def test_row1_src_only_fails_interrupted_and_cleans_created_dirs(tmp_path: Path) -> None:
    env = build_row1(tmp_path)
    out = recover(env)
    assert out.state == "failed"
    assert out.error_code == "INTERRUPTED"
    # The file is untouched at the source; the emptied created folder is gone.
    assert (env.root / "a/one.mp3").read_bytes() == b"audio-bytes"
    assert not (env.root / "a/new").exists()
    # The row still describes the file at its source.
    assert env.row() == ("a/one.mp3", 1, "present")


def test_row1_keeps_a_created_dir_that_is_not_empty(tmp_path: Path) -> None:
    env = build_row1(tmp_path)
    (env.root / "a/new/other.txt").write_bytes(b"not-ours")
    out = recover(env)
    assert out.state == "failed"
    # rmdir_if_empty fails on any entry: the walk stops, the folder stays.
    assert (env.root / "a/new/other.txt").read_bytes() == b"not-ours"
    assert (env.root / "a/one.mp3").read_bytes() == b"audio-bytes"


def test_row1_from_staged_stops_for_a_human(tmp_path: Path) -> None:
    env = build_row2(tmp_path, state="staged")
    # Rebuild the disk picture of row 1 (S only) but from the 'staged' state.
    via = env.root / env.via_rel()
    src = env.root / "a/one.mp3"
    via.rename(src)
    env.set_op("staged", params_for(env))
    out = recover(env)
    # 'staged' has no 'failed' edge in states.ALLOWED: recovery cannot map this
    # picture onto a legal terminal, so it stops for a human instead.
    assert out.state == "needs_attention"
    assert out.error_code == "NEEDS_ATTENTION"
    assert src.read_bytes() == b"case-bytes"


@pytest.mark.parametrize("state", ["intent", "staged"])
def test_row2_via_only_finishes_the_case_only_rename_and_commits(
    tmp_path: Path, state: str
) -> None:
    env = build_row2(tmp_path, state=state)
    out = recover(env)
    assert out.state == "committed"
    # The destination holds the content under the new case; via and src are gone.
    assert os.listdir(env.root / "a") == ["One.mp3"]
    assert not (env.root / env.via_rel()).exists()
    assert env.row() == ("a/One.mp3", 2, "present")
    original = Counter({hashlib.sha256(b"case-bytes").hexdigest(): 1})
    assert_consistent(env.root, env.conn, extra_dirs=(env.work_dir,), original=original)


@pytest.mark.parametrize("state", ["intent", "staged", "applied"])
def test_row3_dst_match_verifies_and_commits(tmp_path: Path, state: str) -> None:
    env = build_row3(tmp_path, state=state)
    out = recover(env)
    assert out.state == "committed"
    assert (env.root / "a/new/one.mp3").read_bytes() == b"moved-bytes"
    assert env.row() == ("a/new/one.mp3", 2, "present")
    original = Counter({hashlib.sha256(b"moved-bytes").hexdigest(): 1})
    assert_consistent(env.root, env.conn, extra_dirs=(env.work_dir,), original=original)


def test_row3_commit_is_replayed_from_a_later_state_without_a_disk_change(
    tmp_path: Path,
) -> None:
    env = build_row3(tmp_path, state="intent")
    snap = env.snapshot()
    out = recover(env)
    assert out.state == "committed"
    # Reaching 'committed' may walk through 'applied', but the disk never changed.
    assert env.snapshot() == snap


def test_row4_dst_mismatch_needs_attention(tmp_path: Path) -> None:
    env = build_row4(tmp_path)
    out = recover(env)
    assert out.state == "needs_attention"
    assert out.error_code == "NEEDS_ATTENTION"
    # The stranger's file is untouched; the op row is left for a human.
    assert (env.root / "a/new/one.mp3").read_bytes() == b"someone-elses-bigger-bytes-data"
    assert env.row() == ("a/one.mp3", 1, "present")


def test_row4_same_size_different_mtime_needs_attention(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"moved-bytes")
    (env.root / "a/one.mp3").unlink()
    dst = env.file_at("a/new/one.mp3", b"moved-bytes", mtime_ns=12345)
    assert dst.stat().st_mtime_ns != env.mtime_ns
    env.set_op("applied", params_for(env))
    out = recover(env)
    assert out.state == "needs_attention"
    assert out.error_code == "NEEDS_ATTENTION"


def test_row5_both_names_exist_needs_attention_and_removes_neither(tmp_path: Path) -> None:
    env = build_row5(tmp_path)
    out = recover(env)
    assert out.state == "needs_attention"
    assert out.error_code == "NEEDS_ATTENTION"
    # Never remove either name: the exFAT power cut can leave two entries
    # sharing one cluster chain, and deleting one frees the other's data.
    assert (env.root / "a/one.mp3").read_bytes() == b"our-content"
    assert (env.root / "a/new/one.mp3").read_bytes() == b"other-content"


def test_row5_case_alias_both_names_needs_attention(tmp_path: Path) -> None:
    if is_case_insensitive(tmp_path):
        pytest.skip("case-insensitive filesystem: 'one.mp3' and 'One.mp3' alias one entry")
    env = build_env(tmp_path, "a/one.mp3", "a/One.mp3", b"alias-content")
    (env.root / "a/One.mp3").write_bytes(b"alias-content-copy")
    env.set_op("staged", params_for(env))
    out = recover(env)
    assert out.state == "needs_attention"
    assert (env.root / "a/one.mp3").read_bytes() == b"alias-content"
    assert (env.root / "a/One.mp3").read_bytes() == b"alias-content-copy"


def test_both_src_and_via_needs_attention_and_removes_neither(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/One.mp3", b"double-content")
    (env.root / env.via_rel()).write_bytes(b"double-content-copy")
    env.set_op("staged", params_for(env))
    out = recover(env)
    assert out.state == "needs_attention"
    assert (env.root / "a/one.mp3").read_bytes() == b"double-content"
    assert (env.root / env.via_rel()).read_bytes() == b"double-content-copy"


def test_both_via_and_dst_needs_attention_and_removes_neither(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/One.mp3", b"double-content")
    (env.root / "a/one.mp3").unlink()
    (env.root / env.via_rel()).write_bytes(b"double-content-copy")
    (env.root / "a/One.mp3").write_bytes(b"other-bytes-at-dst")
    env.set_op("intent", params_for(env))
    out = recover(env)
    assert out.state == "needs_attention"
    assert (env.root / env.via_rel()).read_bytes() == b"double-content-copy"
    assert (env.root / "a/One.mp3").read_bytes() == b"other-bytes-at-dst"


def test_row6_nothing_found_needs_attention(tmp_path: Path) -> None:
    env = build_row6(tmp_path)
    out = recover(env)
    assert out.state == "needs_attention"
    assert out.error_code == "NEEDS_ATTENTION"


# --------------------------------------------------------------------------- #
# planned and terminal ops
# --------------------------------------------------------------------------- #


def test_recover_a_planned_op_reruns_the_move(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"retryable")
    # No disk change ever happens before the op leaves 'planned', so a planned
    # move is fully retryable: recovery drives it to a terminal state.
    out = recover(env)
    assert out.state == "committed"
    assert (env.root / "a/new/one.mp3").read_bytes() == b"retryable"
    assert env.row() == ("a/new/one.mp3", 2, "present")


def test_recover_a_planned_op_whose_source_changed_fails_precondition(
    tmp_path: Path,
) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"original")
    (env.root / "a/one.mp3").write_bytes(b"original-WAS-MODIFIED-longer")
    out = recover(env)
    assert out.state == "failed"
    assert out.error_code == "PRECONDITION_FAILED"
    assert env.row() == ("a/one.mp3", 1, "changed")
    assert not (env.root / "a/new/one.mp3").exists()


@pytest.mark.parametrize("state", ["committed", "failed", "skipped", "needs_attention"])
def test_recover_a_terminal_op_is_a_noop(tmp_path: Path, state: str) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"terminal")
    env.set_op(state)
    n = len(env.records)
    snap = env.snapshot()
    out = recover(env)
    assert out.state == state
    assert env.state() == state
    assert len(env.records) == n  # no transition was recorded
    assert env.snapshot() == snap  # the disk was not touched


def test_recover_move_rejects_a_non_move_op(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"not-a-move")
    repo = OplogRepo(env.conn, mirror=env.records.append, clock=lambda: NOW)
    retag_id = repo.add_op(
        repo.create_batch("rename", "retag", "{}"),
        env.file_id,
        unit_seq=1,
        step_seq=0,
        kind="retag",
        expect=(env.src_rel, env.size, env.mtime_ns, 1),
        params={"path": env.src_rel},
    )
    env.conn.execute("UPDATE operations SET state = 'intent' WHERE op_id = ?", (retag_id,))
    env.conn.commit()
    with pytest.raises(ValueError, match="retag"):
        recover_move(repo.get(retag_id), env.ctx(RealFs()))


# --------------------------------------------------------------------------- #
# idempotency: a second recover call is a no-op
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "builder", ["build_row1", "build_row2", "build_row3", "build_row4", "build_row5", "build_row6"]
)
def test_a_second_recover_call_is_a_noop(tmp_path: Path, builder: str) -> None:
    env = globals()[builder](tmp_path)
    first = recover(env)
    n = len(env.records)
    snap = env.snapshot()
    second = recover(env)
    assert second.state == first.state
    assert env.state() == first.state
    assert len(env.records) == n  # the second call recorded no transition
    assert env.snapshot() == snap  # and touched nothing on disk


# --------------------------------------------------------------------------- #
# extended crash matrix: the P1-13 matrix re-run through recovery
# --------------------------------------------------------------------------- #


def _crash_points_for(env: Env) -> list[tuple[int, str]]:
    n = count_calls(lambda fs: run_move(env.get_op(), env.ctx(fs)), RealFs())
    return [(crash_at, when) for crash_at in range(1, n + 1) for when in ("before", "after")]


@pytest.mark.parametrize(
    "src_rel,dst_rel", [("a/one.mp3", "a/new/one.mp3"), ("a/one.mp3", "a/One.mp3")]
)
def test_crash_matrix_extended_with_recovery(tmp_path: Path, src_rel: str, dst_rel: str) -> None:
    content = b"crash-matrix-content-" + dst_rel.encode()
    original = Counter({hashlib.sha256(content).hexdigest(): 1})

    measure = build_env(tmp_path / "measure", src_rel, dst_rel, content)
    points = _crash_points_for(measure)
    assert points, "the move must make at least one fs call"

    for crash_at, when in points:
        env = build_env(tmp_path / f"crash-{crash_at}-{when}", src_rel, dst_rel, content)
        fault = FaultyFs(RealFs(), crash_at=crash_at, when=when)
        try:
            run_move(env.get_op(), env.ctx(fault))
        except SimulatedCrash:
            pass
        except Exception:  # noqa: BLE001 - a non-crash error means a real bug
            raise
        # Recovery on a fresh engine against the real filesystem.
        recover_move(env.get_op(), env.ctx(RealFs()))
        assert_consistent(env.root, env.conn, extra_dirs=(env.work_dir,), original=original)
        state = env.state()
        assert state in {"committed", "failed"}, (crash_at, when, state)
        # A second recover call is a no-op.
        n = len(env.records)
        snap = env.snapshot()
        recover_move(env.get_op(), env.ctx(RealFs()))
        assert env.state() == state
        assert len(env.records) == n
        assert env.snapshot() == snap
        assert_consistent(env.root, env.conn, extra_dirs=(env.work_dir,), original=original)

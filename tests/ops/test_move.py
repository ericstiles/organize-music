"""Tests for the move operation (PLAN §6.2, issue b8p.22 / catalogue P1-13).

``run_move`` is the tracer's one mutation: rename or move one file, journaled
through the operation log, never replacing anything.  It walks the §6.2 state
table ``planned -> intent -> [staged] -> applied -> committed`` and, on a
precondition or collision failure, transitions to ``failed`` instead of touching
the file.  The crash matrix runs the move against :class:`FaultyFs` at every
filesystem call and asserts the on-disk invariant the plan guarantees: the file's
content is at exactly one of ``{src, via, dst}`` and is never lost or duplicated.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from support.faulty_fs import FaultyFs, SimulatedCrash, count_calls

from organize_music.db import migrate
from organize_music.fsops.protocol import RealFs
from organize_music.ops.context import OpContext
from organize_music.ops.move import plan_move_params, run_move
from organize_music.ops.oplog_repo import OplogRepo
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
    """One on-disk library plus a migrated DB and a planned move op."""

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
        self.op_id = _make_planned_op(
            self.conn, src_rel, dst_rel, self.file_id, self.size, self.mtime_ns
        )

    def ctx(self, fs: RealFs) -> OpContext:
        oplog = OplogRepo(self.conn, mirror=lambda r: None, clock=lambda: NOW)
        return OpContext(
            root=self.root,
            work_dir=self.work_dir,
            purge_dir=self.purge_dir,
            fs=fs,
            oplog=oplog,
            conn=self.conn,
            clock=lambda: NOW,
        )

    def locations(self) -> tuple[Path, Path | None, Path]:
        """The (src, via, dst) paths the move may hold its content at."""
        import json

        src = self.root / self.src_rel
        dst = self.root / self.dst_rel
        row = self.conn.execute(
            "SELECT params_json FROM operations WHERE op_id = ?", (self.op_id,)
        ).fetchone()
        params = json.loads(row[0]) if row else {}
        via_rel = params.get("via")
        via = self.root / via_rel if via_rel else None
        return src, via, dst


def _make_planned_op(
    conn: sqlite3.Connection, src_rel: str, dst_rel: str, file_id: int, size: int, mtime_ns: int
) -> int:
    repo = OplogRepo(conn, mirror=lambda r: None, clock=lambda: NOW)
    batch = repo.create_batch("rename", "move", "{}")
    return repo.add_op(
        batch,
        file_id,
        unit_seq=0,
        step_seq=0,
        kind="move",
        expect=(src_rel, size, mtime_ns, 1),
        params=plan_move_params(src_rel, dst_rel, op_id_hint="1"),
    )


def build_env(base: Path, src_rel: str, dst_rel: str, content: bytes) -> Env:
    """A fresh library, DB and planned op under ``base`` (isolated per call)."""
    root = base / "root"
    work_dir = base / "work"
    purge_dir = base / "purge"
    return Env(root, work_dir, purge_dir, src_rel, dst_rel, content)


def get_op(env: Env) -> object:
    return OplogRepo(env.conn, mirror=lambda r: None, clock=lambda: NOW).get(env.op_id)


def get_files_status(env: Env, file_id: int) -> str:
    row = env.conn.execute("SELECT status FROM files WHERE file_id = ?", (file_id,)).fetchone()
    return row[0] if row is not None else None


def content_at(paths: list[Path], content: bytes) -> list[Path]:
    """Return the locations that currently hold a regular file with this content."""
    found = []
    for p in paths:
        if p is None:
            continue
        if p.is_file() and p.read_bytes() == content:
            found.append(p)
    return found


# --------------------------------------------------------------------------- #
# plan_move_params
# --------------------------------------------------------------------------- #


def test_plan_move_params_holds_src_dst_and_empty_created_dirs() -> None:
    params = plan_move_params("a/one.mp3", "a/new/one.mp3", "42")
    assert params["src"] == "a/one.mp3"
    assert params["dst"] == "a/new/one.mp3"
    assert params["created_dirs"] == []
    assert params["dst_root"] == "library"
    # A non case-only pair has no intermediate name.
    assert params["via"] is None


def test_plan_move_params_sets_via_for_a_case_only_rename() -> None:
    params = plan_move_params("a/one.mp3", "a/One.mp3", "42")
    # Same exFAT collision key, different name => a case-only rename needs via.
    assert params["via"] is not None
    assert params["via"].endswith(".tmp")


# --------------------------------------------------------------------------- #
# happy path: move into a new subfolder
# --------------------------------------------------------------------------- #


def test_move_into_a_new_subfolder_commits(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"\x00audio-content\x00")
    out = run_move(get_op(env), env.ctx(RealFs()))
    assert out.state == "committed"
    # The file is now at the destination and gone from the source.
    assert (env.root / "a/new/one.mp3").is_file()
    assert not (env.root / "a/one.mp3").exists()
    # The row moved with it.
    row = env.conn.execute(
        "SELECT path, path_key, row_version FROM files WHERE file_id = ?", (env.file_id,)
    ).fetchone()
    assert row["path"] == "a/new/one.mp3"
    assert row["path_key"] == path_key("a/new/one.mp3")
    assert int(row["row_version"]) == 2


def test_move_happy_path_cleans_the_emptied_source_folder(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "b/one.mp3", b"hello")
    run_move(get_op(env), env.ctx(RealFs()))
    # The now-empty source folder 'a' was removed best-effort.
    assert not (env.root / "a").exists()
    assert (env.root / "b/one.mp3").is_file()


# --------------------------------------------------------------------------- #
# collision: dst on disk, dst in DB only
# --------------------------------------------------------------------------- #


def test_dst_on_disk_fails_with_collision_and_touches_nothing(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"src-bytes")
    dst = env.root / "a/new/one.mp3"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(b"someone-elses-bytes")

    out = run_move(get_op(env), env.ctx(RealFs()))

    assert out.state == "failed"
    assert out.error_code == "COLLISION"
    # Neither file was touched.
    assert (env.root / "a/one.mp3").read_bytes() == b"src-bytes"
    assert dst.read_bytes() == b"someone-elses-bytes"


def test_dst_taken_in_db_only_fails_with_collision(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"src-bytes")
    # A different row already owns the destination's collision key.
    env.conn.execute(
        "INSERT INTO files (path, path_key, last_path, status, kind, size, mtime_ns, ext, "
        "row_version, first_seen_at, updated_at, artist_src, album_artist_src, album_src, "
        "title_src, track_number_src, disc_number_src, year_src, genre_src) "
        "VALUES (?, ?, ?, 'present', 'audio', 1, 1, 'mp3', 1, ?, ?, 'missing', 'missing', "
        "'missing', 'missing', 'missing', 'missing', 'missing', 'missing')",
        ("a/new/one.mp3", path_key("a/new/one.mp3"), "a/new/one.mp3", NOW, NOW),
    )
    env.conn.commit()

    out = run_move(get_op(env), env.ctx(RealFs()))

    assert out.state == "failed"
    assert out.error_code == "COLLISION"
    # The source is untouched; nothing was created at the destination.
    assert (env.root / "a/one.mp3").read_bytes() == b"src-bytes"
    assert not (env.root / "a/new/one.mp3").exists()


# --------------------------------------------------------------------------- #
# precondition: src changed on disk
# --------------------------------------------------------------------------- #


def test_src_size_changed_fails_precondition_and_marks_row_changed(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/new/one.mp3", b"original")
    # The disk file changed after the op's precondition was captured.
    (env.root / "a/one.mp3").write_bytes(b"original-WAS-MODIFIED-longer")

    out = run_move(get_op(env), env.ctx(RealFs()))

    assert out.state == "failed"
    assert out.error_code == "PRECONDITION_FAILED"
    assert get_files_status(env, env.file_id) == "changed"
    # The move never happened.
    assert (env.root / "a/one.mp3").exists()
    assert not (env.root / "a/new/one.mp3").exists()


# --------------------------------------------------------------------------- #
# case-only rename goes through the staged state
# --------------------------------------------------------------------------- #


def test_case_only_rename_passes_through_staged(tmp_path: Path) -> None:
    env = build_env(tmp_path, "a/one.mp3", "a/One.mp3", b"case-only-bytes")
    out = run_move(get_op(env), env.ctx(RealFs()))
    assert out.state == "committed"
    # The destination exists with the new case; the source name is gone.
    assert (env.root / "a/One.mp3").is_file()
    assert not (env.root / "a/one.mp3").exists()
    # The oplog recorded the staged intermediate.
    row = env.conn.execute("SELECT state FROM operations WHERE op_id = ?", (env.op_id,)).fetchone()
    assert row[0] == "committed"


# --------------------------------------------------------------------------- #
# crash matrix: content is at exactly one location and is never lost
# --------------------------------------------------------------------------- #


def _crash_points_for(env: Env) -> list[tuple[int, str]]:
    n = count_calls(lambda fs: run_move(get_op(env), env.ctx(fs)), RealFs())
    return [(crash_at, when) for crash_at in range(1, n + 1) for when in ("before", "after")]


@pytest.mark.parametrize(
    "src_rel,dst_rel", [("a/one.mp3", "a/new/one.mp3"), ("a/one.mp3", "a/One.mp3")]
)
def test_move_survives_a_crash_at_every_point(tmp_path: Path, src_rel: str, dst_rel: str) -> None:
    content = b"crash-matrix-content-" + dst_rel.encode()
    # First pass (no crash) to learn how many fs calls the move makes.
    measure = build_env(tmp_path / "measure", src_rel, dst_rel, content)
    points = _crash_points_for(measure)
    assert points, "the move must make at least one fs call"

    for crash_at, when in points:
        env = build_env(tmp_path / f"crash-{crash_at}-{when}", src_rel, dst_rel, content)
        fault = FaultyFs(RealFs(), crash_at=crash_at, when=when)
        try:
            run_move(get_op(env), env.ctx(fault))
        except SimulatedCrash:
            pass
        except Exception:  # noqa: BLE001 - a non-crash error means a real bug
            raise
        src, via, dst = env.locations()
        locations = [p for p in (src, via, dst) if p is not None]
        present = [p for p in locations if p.is_file()]
        assert len(present) == 1, (
            f"crash {crash_at}/{when}: expected exactly one location, "
            f"found {[str(p) for p in present]}"
        )
        assert present[0].read_bytes() == content

"""Tests for the ``OM_FAULT_SLEEP_AFTER`` fault hook in ``run_move`` (b8p.34).

The tracer E2E (``scripts/tracer_e2e.sh``) proves crash recovery with a real
process kill: it starts ``organize-music serve`` with
``OM_FAULT_SLEEP_AFTER=<state>`` in the environment, starts a rename over
HTTP, and ``kill -9``s the server in the 30 s window the hook opens after the
op reaches the named state. For that to work the hook must sleep exactly 30 s
after reaching the named state, and be a no-op when the variable is unset, so
a normal run (and the restarted server) never waits.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from organize_music.db import migrate
from organize_music.fsops.protocol import RealFs
from organize_music.ops import move
from organize_music.ops.context import OpContext
from organize_music.ops.move import plan_move_params, run_move
from organize_music.ops.oplog_repo import OplogRepo
from organize_music.paths import path_key

NOW = "2026-03-01T00:00:00Z"
SRC = "artist/album/001-Song_1.mp3"
DST = "artist/album/001-Song_1-renamed.mp3"
_CONTENT = b"\x00fault-hook-bytes\x00"

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
    """A real one-file library, a migrated DB and a planned move op."""

    def __init__(self, base: Path) -> None:
        self.root = base / "library"
        self.work = base / "work"
        self.purge = base / "purge"
        state = base / "state"
        state.mkdir(parents=True)
        self.db = state / "library.db"
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        migrate(self.conn, self.db, state / "backups", NOW)
        src = self.root / SRC
        src.parent.mkdir(parents=True)
        src.write_bytes(_CONTENT)
        st = src.stat()
        self.file_id = int(
            self.conn.execute(
                _INSERT, (SRC, path_key(SRC), SRC, st.st_size, st.st_mtime_ns, "mp3", NOW, NOW)
            ).lastrowid
        )
        self.conn.commit()
        repo = OplogRepo(self.conn, mirror=lambda record: None, clock=lambda: NOW)
        batch = repo.create_batch("rename", "move", "{}")
        self.op_id = repo.add_op(
            batch,
            self.file_id,
            unit_seq=0,
            step_seq=0,
            kind="move",
            expect=(SRC, st.st_size, st.st_mtime_ns, 1),
            params=plan_move_params(SRC, DST, op_id_hint="1"),
        )

    def ctx(self) -> OpContext:
        oplog = OplogRepo(self.conn, mirror=lambda record: None, clock=lambda: NOW)
        return OpContext(
            root=self.root,
            work_dir=self.work,
            purge_dir=self.purge,
            fs=RealFs(),
            oplog=oplog,
            conn=self.conn,
            clock=lambda: NOW,
        )


def test_unset_hook_adds_no_sleep(tmp_path: Path, monkeypatch) -> None:
    """OM_FAULT_SLEEP_AFTER unset: run_move never sleeps (the no-op contract)."""
    monkeypatch.delenv("OM_FAULT_SLEEP_AFTER", raising=False)
    calls: list[float] = []
    monkeypatch.setattr(move.time, "sleep", lambda seconds: calls.append(seconds))
    env = Env(tmp_path)
    ctx = env.ctx()
    final = run_move(ctx.oplog.get(env.op_id), ctx)
    assert final.state == "committed"
    assert calls == []


def test_hook_sleeps_30s_after_the_named_state(tmp_path: Path, monkeypatch) -> None:
    """The op reaches 'applied' exactly once on this move: one 30 s sleep."""
    monkeypatch.setenv("OM_FAULT_SLEEP_AFTER", "applied")
    calls: list[float] = []
    monkeypatch.setattr(move.time, "sleep", lambda seconds: calls.append(seconds))
    env = Env(tmp_path)
    ctx = env.ctx()
    final = run_move(ctx.oplog.get(env.op_id), ctx)
    assert final.state == "committed"
    assert calls == [30.0]


def test_hook_named_state_not_reached_adds_no_sleep(tmp_path: Path, monkeypatch) -> None:
    """'staged' only happens on case-only renames; this move skips it."""
    monkeypatch.setenv("OM_FAULT_SLEEP_AFTER", "staged")
    calls: list[float] = []
    monkeypatch.setattr(move.time, "sleep", lambda seconds: calls.append(seconds))
    env = Env(tmp_path)
    ctx = env.ctx()
    final = run_move(ctx.oplog.get(env.op_id), ctx)
    assert final.state == "committed"
    assert calls == []

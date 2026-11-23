"""Tests for the operation log repository (PLAN §6.2/§6.3, issue b8p.16).

``OplogRepo`` is the crash-safe heart of a move: every operation moves only
through the states in :data:`organize_music.ops.states.ALLOWED`, and each
transition is one durable transaction that runs an optional ``extra`` (the
files-table write, e.g. ``files_write.update_path``) and the op-state update
together, commits, and then mirrors the record. A transition that is not
allowed, or whose ``extra`` raises, writes nothing. The partial unique index
``operations_one_active_per_file`` keeps at most one active op per file.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from organize_music.db import migrate
from organize_music.ops.oplog_repo import IllegalTransition, OplogRepo
from organize_music.ops.states import ACTIVE, ALLOWED, is_allowed


def open_conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrated(tmp_path: Path) -> sqlite3.Connection:
    """A fresh, migrated library.db (version 1) with a writer connection."""
    path = tmp_path / "library.db"
    conn = open_conn(path)
    migrate(conn, path, tmp_path / "backups", "2026-01-01T00:00:00Z")
    return conn


# The same column list the crash-test harness uses (tests/support/test_support.py):
# every column the 0001 schema requires for a present audio row.
_INSERT = (
    "INSERT INTO files "
    "(path, path_key, last_path, status, kind, size, mtime_ns, ext, "
    "artist, artist_src, album_artist, album_artist_src, album, album_src, "
    "title, title_src, track_number, track_number_src, disc_number, "
    "disc_number_src, year, year_src, genre, genre_src, row_version, "
    "first_seen_at, updated_at) "
    "VALUES (?, ?, ?, 'present', 'audio', ?, ?, ?, "
    "'a', 'tag', 'a', 'tag', 'a', 'tag', 't', 'tag', '1', 'tag', '1', 'tag', "
    "'2001', 'tag', 'Rock', 'tag', 1, '2026-01-01T00:00:00Z', "
    "'2026-01-01T00:00:00Z')"
)


def insert_file(conn: sqlite3.Connection, rel: str, size: int = 1024, mtime_ns: int = 1_700) -> int:
    """Insert a present audio row and return its file_id."""
    cur = conn.execute(_INSERT, (rel, rel.casefold(), rel, size, mtime_ns, "mp3"))
    conn.commit()
    return int(cur.lastrowid)


def make_repo(conn: sqlite3.Connection, records: list) -> OplogRepo:
    """A repo mirroring every transition into ``records`` with a fixed clock."""
    return OplogRepo(conn, mirror=records.append, clock=lambda: "2026-02-01T00:00:00Z")


def add_move(repo: OplogRepo, batch_id: int, file_id: int, step_seq: int = 0) -> int:
    return repo.add_op(
        batch_id,
        file_id,
        unit_seq=0,
        step_seq=step_seq,
        kind="move",
        expect=("a/one.mp3", 1024, 1_700, 1),
        params={"new_path": "albums/one.mp3"},
    )


def _drive(repo: OplogRepo, op_id: int, target: str) -> None:
    """Drive an op to ``target`` by following legal transitions from 'planned'.

    The move/retag state graph is not a single chain (``intent`` may go to
    ``applied`` directly, and ``staged`` is a branch), so walk it with a BFS
    over :data:`organize_music.ops.states.ALLOWED` and apply each step.
    """
    kind = repo.get(op_id).kind
    start = repo.get(op_id).state
    if start == target:
        return
    path = _bfs(kind, start, target)
    # path is [start, ..., target]; apply the transitions from the second node on.
    for step in path[1:]:
        repo.transition(op_id, step)


def _bfs(kind: str, start: str, target: str) -> list[str]:
    """The legal state path ``[start, ... , target]`` (empty if unreachable)."""
    seen = {start}
    parent: dict[str, str | None] = {start: None}
    frontier = [start]
    while frontier:
        current = frontier.pop(0)
        for nxt in ALLOWED.get((kind, current), frozenset()):
            if nxt in seen:
                continue
            seen.add(nxt)
            parent[nxt] = current
            if nxt == target:
                path = [nxt]
                node = nxt
                while parent[node] is not None:
                    node = parent[node]  # type: ignore[assignment]
                    path.append(node)
                return path[::-1]
            frontier.append(nxt)
    return []


# --------------------------------------------------------------------------- #
# create_batch / add_op / get
# --------------------------------------------------------------------------- #


def test_create_batch_returns_an_increasing_id(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    repo = make_repo(conn, [])
    a = repo.create_batch("rename", "first", "{}")
    b = repo.create_batch("edit", "second", "{}")
    assert a + 1 == b
    row = conn.execute(
        "SELECT kind, state, description, request_json FROM batches WHERE batch_id = ?", (a,)
    ).fetchone()
    assert row["kind"] == "rename"
    assert row["state"] == "draft"
    assert row["description"] == "first"
    assert row["request_json"] == "{}"


def test_add_op_starts_planned_and_round_trips(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    fid = insert_file(conn, "a/one.mp3")
    repo = make_repo(conn, [])
    batch = repo.create_batch("rename", "b", "{}")
    op_id = repo.add_op(batch, fid, 0, 0, "move", ("a/one.mp3", 1024, 1_700, 1), {"p": 1})
    op = repo.get(op_id)
    assert op.op_id == op_id
    assert op.batch_id == batch
    assert op.file_id == fid
    assert op.unit_seq == 0
    assert op.step_seq == 0
    assert op.kind == "move"
    assert op.state == "planned"
    assert op.expect_path == "a/one.mp3"
    assert op.expect_size == 1024
    assert op.expect_mtime_ns == 1_700
    assert op.expect_row_version == 1
    assert op.params == {"p": 1}
    assert op.error_code is None


# --------------------------------------------------------------------------- #
# allowed transitions
# --------------------------------------------------------------------------- #

# Every (kind, from, to) the plan permits. Each must succeed.
ALLOWED_CASES = [
    ("move", "planned", "intent"),
    ("move", "planned", "failed"),
    ("move", "planned", "skipped"),
    ("move", "intent", "applied"),
    ("move", "intent", "staged"),
    ("move", "intent", "failed"),
    ("move", "intent", "needs_attention"),
    ("move", "staged", "applied"),
    ("move", "staged", "needs_attention"),
    ("move", "applied", "committed"),
    ("move", "applied", "needs_attention"),
    ("retag", "planned", "intent"),
    ("retag", "planned", "failed"),
    ("retag", "planned", "skipped"),
    ("retag", "intent", "staged"),
    ("retag", "intent", "failed"),
    ("retag", "intent", "needs_attention"),
    ("retag", "staged", "parked"),
    ("retag", "staged", "failed"),
    ("retag", "staged", "needs_attention"),
    ("retag", "parked", "applied"),
    ("retag", "parked", "failed"),
    ("retag", "parked", "needs_attention"),
    ("retag", "applied", "committed"),
    ("retag", "applied", "needs_attention"),
]


@pytest.mark.parametrize("kind,frm,to", ALLOWED_CASES)
def test_every_allowed_transition_succeeds(tmp_path: Path, kind: str, frm: str, to: str) -> None:
    assert is_allowed(kind, frm, to)
    conn = migrated(tmp_path)
    fid = insert_file(conn, "a/one.mp3")
    repo = make_repo(conn, [])
    batch = repo.create_batch("rename" if kind == "move" else "edit", "b", "{}")
    op_id = repo.add_op(batch, fid, 0, 0, kind, ("a/one.mp3", 1024, 1_700, 1), {})
    _drive(repo, op_id, frm)
    out = repo.transition(op_id, to)
    assert out.state == to


# A table of disallowed transitions: each must raise and leave the row untouched.
DISALLOWED_CASES = [
    ("move", "planned", "committed"),  # skip straight to a terminal
    ("move", "planned", "staged"),  # two steps at once
    ("move", "intent", "committed"),  # must pass through applied
    ("move", "committed", "intent"),  # terminal: nothing
    ("move", "committed", "needs_attention"),
    ("move", "failed", "intent"),  # terminal: nothing
    ("retag", "planned", "parked"),  # must pass through intent/staged
    ("retag", "staged", "applied"),  # must pass through parked
    ("retag", "intent", "applied"),  # must pass through staged/parked
    ("retag", "committed", "needs_attention"),  # terminal
    ("move", "staged", "staged"),  # self, not listed
]


@pytest.mark.parametrize("kind,frm,to", DISALLOWED_CASES)
def test_disallowed_transition_raises_and_leaves_row_unchanged(
    tmp_path: Path, kind: str, frm: str, to: str
) -> None:
    assert not is_allowed(kind, frm, to)
    conn = migrated(tmp_path)
    fid = insert_file(conn, "a/one.mp3")
    repo = make_repo(conn, [])
    batch = repo.create_batch("rename" if kind == "move" else "edit", "b", "{}")
    op_id = repo.add_op(batch, fid, 0, 0, kind, ("a/one.mp3", 1024, 1_700, 1), {})
    _drive(repo, op_id, frm)
    before = repo.get(op_id)
    with pytest.raises(IllegalTransition):
        repo.transition(op_id, to)
    after = repo.get(op_id)
    assert after.state == before.state
    assert after == before


def test_failed_transition_records_error(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    fid = insert_file(conn, "a/one.mp3")
    records: list = []
    repo = make_repo(conn, records)
    batch = repo.create_batch("rename", "b", "{}")
    op_id = add_move(repo, batch, fid)
    out = repo.transition(op_id, "failed", error=("E_NOFILE", "the source vanished"))
    assert out.state == "failed"
    assert out.error_code == "E_NOFILE"
    assert len(records) == 1  # a legal transition still mirrors once


# --------------------------------------------------------------------------- #
# extra() and atomicity
# --------------------------------------------------------------------------- #


def test_extra_runs_inside_the_transaction_and_is_seen_after_commit(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    fid = insert_file(conn, "a/one.mp3")
    records: list = []
    repo = make_repo(conn, records)
    batch = repo.create_batch("rename", "b", "{}")
    op_id = add_move(repo, batch, fid)
    _drive(repo, op_id, "intent")

    def extra(c: sqlite3.Connection) -> None:
        # Mimic files_write.update_path: write the row, commit nothing.
        c.execute(
            "UPDATE files SET path = ?, path_key = ? WHERE file_id = ?",
            ("albums/one.mp3", "albums/one.mp3", fid),
        )

    out = repo.transition(op_id, "applied", extra=extra)
    assert out.state == "applied"
    row = conn.execute("SELECT path FROM files WHERE file_id = ?", (fid,)).fetchone()
    assert row["path"] == "albums/one.mp3"
    # _drive to 'intent' mirrored once; the 'applied' transition mirrors again.
    assert len(records) == 2


def test_extra_that_raises_leaves_op_and_files_unchanged(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    fid = insert_file(conn, "a/one.mp3")
    records: list = []
    repo = make_repo(conn, records)
    batch = repo.create_batch("rename", "b", "{}")
    op_id = add_move(repo, batch, fid)
    _drive(repo, op_id, "intent")

    def boom(c: sqlite3.Connection) -> None:
        c.execute("UPDATE files SET size = 99999 WHERE file_id = ?", (fid,))
        raise RuntimeError("disk full")

    try:
        repo.transition(op_id, "applied", extra=boom)
    except RuntimeError:
        pass
    else:
        raise AssertionError("expected the RuntimeError to propagate")
    # Neither the op nor the files row changed; nothing was committed, and the
    # 'applied' transition did not mirror (only the earlier 'intent' did).
    assert repo.get(op_id).state == "intent"
    row = conn.execute("SELECT size FROM files WHERE file_id = ?", (fid,)).fetchone()
    assert int(row["size"]) == 1024
    assert len(records) == 1  # the 'intent' drive; no mirror for the failed 'applied'


# --------------------------------------------------------------------------- #
# mirror
# --------------------------------------------------------------------------- #


def test_mirror_called_once_per_success_and_not_on_failure(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    fid = insert_file(conn, "a/one.mp3")
    records: list = []
    repo = make_repo(conn, records)
    batch = repo.create_batch("rename", "b", "{}")
    op_id = add_move(repo, batch, fid)
    repo.transition(op_id, "intent")
    repo.transition(op_id, "applied")
    assert len(records) == 2
    # A disallowed transition adds nothing to the mirror.
    with pytest.raises(IllegalTransition):
        repo.transition(op_id, "intent")  # applied->intent is not allowed
    assert len(records) == 2


def test_mirror_record_carries_the_transition(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    fid = insert_file(conn, "a/one.mp3")
    records: list = []
    repo = make_repo(conn, records)
    batch = repo.create_batch("rename", "b", "{}")
    op_id = add_move(repo, batch, fid)
    repo.transition(op_id, "intent", params={"new_path": "albums/one.mp3"})
    (record,) = records
    assert record["op_id"] == op_id
    assert record["kind"] == "move"
    assert record["state"] == "intent"
    assert record["from_state"] == "planned"
    assert json.dumps(record)  # is JSON-serialisable


# --------------------------------------------------------------------------- #
# the one-active-op-per-file index
# --------------------------------------------------------------------------- #


def test_two_active_ops_on_one_file_are_prevented(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    fid = insert_file(conn, "a/one.mp3")
    repo = make_repo(conn, [])
    batch = repo.create_batch("rename", "b", "{}")
    op_a = repo.add_op(batch, fid, 0, 0, "move", ("a/one.mp3", 1024, 1_700, 1), {})
    op_b = repo.add_op(batch, fid, 0, 1, "move", ("a/one.mp3", 1024, 1_700, 1), {})
    # Both start 'planned' (not active), so the index is happy.
    repo.transition(op_a, "intent")
    assert [o.op_id for o in repo.active_ops()] == [op_a]
    # A second active op on the same file violates the partial unique index.
    with pytest.raises(sqlite3.IntegrityError):
        repo.transition(op_b, "intent")
    # op_b stayed 'planned'; only op_a is active.
    assert repo.get(op_b).state == "planned"
    assert [o.op_id for o in repo.active_ops()] == [op_a]


def test_active_ops_lists_only_active_states_ordered_by_op_id(tmp_path: Path) -> None:
    conn = migrated(tmp_path)
    fid = insert_file(conn, "a/one.mp3")
    fid2 = insert_file(conn, "a/two.mp3")
    repo = make_repo(conn, [])
    batch = repo.create_batch("rename", "b", "{}")
    op_active = repo.add_op(batch, fid, 0, 0, "move", ("a/one.mp3", 1024, 1_700, 1), {})
    op_planned = repo.add_op(batch, fid2, 0, 1, "move", ("a/two.mp3", 1024, 1_700, 1), {})
    repo.transition(op_active, "intent")
    # op_planned is still 'planned', so active_ops returns only op_active.
    assert repo.get(op_planned).state == "planned"
    assert [o.op_id for o in repo.active_ops()] == [op_active]
    # The ACTIVE set is exactly the partial index's predicate.
    assert ACTIVE == frozenset({"intent", "staged", "parked", "applied"})

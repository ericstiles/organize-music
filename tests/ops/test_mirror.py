"""Tests for the JSONL operation mirror on the SSD (b8p.18, plan C1 / §6.1 step 4).

The mirror is the second copy of operation history the plan keeps on the SSD so
that, if ``library.db`` is lost, history can be rebuilt from it. Every record is
one JSON object written as a single line and fsynced, so a crash leaves the file
with only complete records. ``make_mirror`` adapts a ``clock`` into the callable
:mod:`organize_music.ops.oplog_repo` injects as its ``mirror``.
"""

import json
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path

from organize_music.db import migrate
from organize_music.ops.mirror import append, make_mirror, mirror_path


def seq_clock(values: list[str]) -> Callable[[], str]:
    """A callable clock that hands back each ``values`` entry once, in order.

    A ``clock`` is a ``Callable[[], str]``, so ``iter(...)`` is the wrong shape
    (it is not callable); this adapter makes the per-call sequence callable.
    """
    it = iter(values)
    return lambda: next(it)


def lines(path: Path) -> list[dict]:
    """The parsed records in a mirror file, in file order."""
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_mirror_path_is_the_monthly_file(tmp_path: Path) -> None:
    p = mirror_path(tmp_path, "2026-02-15T09:00:00Z")
    assert p == tmp_path / "oplog" / "2026-02.jsonl"
    # The month comes from the first seven characters of ``now`` (YYYY-MM).
    assert mirror_path(tmp_path, "2026-12-01T00:00:00Z") == tmp_path / "oplog" / "2026-12.jsonl"


def test_two_appends_produce_two_lines_in_order(tmp_path: Path) -> None:
    append(tmp_path, {"op_id": 1, "state": "intent"}, "2026-02-01T00:00:00Z")
    append(tmp_path, {"op_id": 2, "state": "applied"}, "2026-02-01T01:00:00Z")
    p = mirror_path(tmp_path, "2026-02-01T00:00:00Z")
    expected = [
        json.dumps({"op_id": 1, "state": "intent"}, sort_keys=True, ensure_ascii=False),
        json.dumps({"op_id": 2, "state": "applied"}, sort_keys=True, ensure_ascii=False),
    ]
    assert p.read_text(encoding="utf-8").splitlines() == expected


def test_month_rollover_writes_to_a_new_file(tmp_path: Path) -> None:
    append(tmp_path, {"n": 1}, "2026-02-01T00:00:00Z")
    append(tmp_path, {"n": 2}, "2026-03-01T00:00:00Z")
    feb = mirror_path(tmp_path, "2026-02-01T00:00:00Z")
    mar = mirror_path(tmp_path, "2026-03-01T00:00:00Z")
    assert feb != mar
    assert lines(feb) == [{"n": 1}]
    assert lines(mar) == [{"n": 2}]


def test_append_uses_json_sorted_and_unicode_safe(tmp_path: Path) -> None:
    append(tmp_path, {"b": 2, "a": 1, "café": "naïve"}, "2026-02-01T00:00:00Z")
    (line,) = mirror_path(tmp_path, "2026-02-01T00:00:00Z").read_text().splitlines()
    expected = json.dumps({"b": 2, "a": 1, "café": "naïve"}, sort_keys=True, ensure_ascii=False)
    assert line == expected
    # The keys are sorted, so "a" precedes "b" in the bytes.
    assert line.index('"a"') < line.index('"b"')
    # ensure_ascii=False keeps non-ASCII characters as UTF-8, not \uXXXX escapes.
    assert "café" in line and "\\u" not in line


def test_append_fsyncs_the_record(tmp_path: Path) -> None:
    # The plan fsyncs every mirror record so a crash leaves only complete lines;
    # spy on os.fsync so the test does not depend on the platform's fsync cost.
    calls: list[int] = []
    real_fsync = os.fsync
    try:
        os.fsync = lambda fd: calls.append(fd)  # type: ignore[assignment]
        append(tmp_path, {"op_id": 7}, "2026-02-01T00:00:00Z")
    finally:
        os.fsync = real_fsync
    assert calls, "append must fsync the file descriptor after writing the record"
    assert all(isinstance(fd, int) for fd in calls)


def test_append_creates_the_monthly_directory(tmp_path: Path) -> None:
    # The oplog dir does not exist yet; append must mkdir -p it.
    assert not (tmp_path / "oplog").exists()
    append(tmp_path, {"op_id": 1}, "2026-02-01T00:00:00Z")
    assert (tmp_path / "oplog").is_dir()
    assert mirror_path(tmp_path, "2026-02-01T00:00:00Z").exists()


def test_make_mirror_appends_using_the_clock(tmp_path: Path) -> None:
    now = "2026-04-10T12:00:00Z"
    m = make_mirror(tmp_path, lambda: now)
    m({"op_id": 3, "state": "staged"})
    p = mirror_path(tmp_path, now)
    assert lines(p) == [{"op_id": 3, "state": "staged"}]


def test_make_mirror_clock_advances_the_month(tmp_path: Path) -> None:
    m = make_mirror(tmp_path, seq_clock(["2026-02-01T00:00:00Z", "2026-03-01T00:00:00Z"]))
    m({"n": 1})
    m({"n": 2})
    assert lines(mirror_path(tmp_path, "2026-02-01T00:00:00Z")) == [{"n": 1}]
    assert lines(mirror_path(tmp_path, "2026-03-01T00:00:00Z")) == [{"n": 2}]


def test_make_mirror_appends_to_the_same_file_within_a_month(tmp_path: Path) -> None:
    # make_mirror keeps the work dir, so two records in the same month land in one
    # file, one line each, in call order (the shape oplog_repo injects).
    m = make_mirror(tmp_path, seq_clock(["2026-02-01T00:00:00Z", "2026-02-05T00:00:00Z"]))
    m({"op_id": 1})
    m({"op_id": 2})
    p = mirror_path(tmp_path, "2026-02-01T00:00:00Z")
    assert lines(p) == [{"op_id": 1}, {"op_id": 2}]


def test_make_mirror_appends_through_an_oplog_repo(tmp_path: Path) -> None:
    # End to end: the callable make_mirror returns is exactly the shape OplogRepo
    # injects as its ``mirror`` (one mapping per transition, returns None).
    from organize_music.ops.oplog_repo import OplogRepo

    path = tmp_path / "library.db"
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    migrate(conn, path, tmp_path / "backups", "2026-01-01T00:00:00Z")
    # operations references files, so a present audio row must exist for the op.
    conn.execute(
        "INSERT INTO files "
        "(path, path_key, last_path, status, kind, size, mtime_ns, ext, "
        "artist, artist_src, album_artist, album_artist_src, album, album_src, "
        "title, title_src, track_number, track_number_src, disc_number, "
        "disc_number_src, year, year_src, genre, genre_src, row_version, "
        "first_seen_at, updated_at) "
        "VALUES ('a/one.mp3', 'a/one.mp3', 'a/one.mp3', 'present', 'audio', 1024, 1, 'mp3', "
        "'a', 'tag', 'a', 'tag', 'a', 'tag', 't', 'tag', '1', 'tag', '1', 'tag', "
        "'2001', 'tag', 'Rock', 'tag', 1, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    fid = int(conn.execute("SELECT file_id FROM files LIMIT 1").fetchone()["file_id"])
    conn.commit()
    clock = lambda: "2026-02-01T00:00:00Z"  # noqa: E731
    repo = OplogRepo(conn, mirror=make_mirror(tmp_path / "work", clock), clock=clock)
    batch = repo.create_batch("rename", "b", "{}")
    expect = ("a/one.mp3", 1024, 1, 1)
    params = {"new_path": "b/one.mp3"}
    op_id = repo.add_op(batch, fid, 0, 0, "move", expect, params)
    repo.transition(op_id, "intent")
    (record,) = lines(mirror_path(tmp_path / "work", "2026-02-01T00:00:00Z"))
    assert record["op_id"] == op_id
    assert record["kind"] == "move"
    assert record["state"] == "intent"
    assert record["from_state"] == "planned"

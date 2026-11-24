"""The JSONL operation mirror on the SSD (b8p.18, plan C1 / §6.1 step 4).

If ``library.db`` is lost or corrupt, the JSONL mirror is the second copy of
operation history, on a second device, from which the history can be rebuilt
(plan C1). It is the last durable step of every move (§6.1 step 4): the DB
write commits first, then the transition is appended here as one record.

Each record is one JSON object written as a single line and fsynced, so a
crash mid-move leaves the file holding only complete records. Records are
grouped into one file per calendar month, named ``YYYY-MM.jsonl`` under
``work_dir/'oplog'``; no rotation beyond the monthly file name.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from pathlib import Path


def mirror_path(work_dir: Path, now: str) -> Path:
    """The monthly mirror file for ``now``: ``work_dir/'oplog'/f'{YYYY-MM}.jsonl'``.

    The month is the first seven characters of ``now`` (the ``YYYY-MM`` prefix
    of an ISO-8601 UTC timestamp).
    """
    return work_dir / "oplog" / f"{now[:7]}.jsonl"


def append(work_dir: Path, record: Mapping[str, object], now: str) -> None:
    """Append ``record`` as one JSON line to the month's mirror, then fsync it.

    The ``oplog`` directory (and any missing parents) is created. The record is
    serialized with sorted keys and ``ensure_ascii=False`` so the line is stable
    and keeps non-ASCII characters as UTF-8; a trailing newline separates it
    from the next. ``flush`` plus ``os.fsync`` on the descriptor is what makes
    the line durable on the SSD before the function returns.
    """
    path = mirror_path(work_dir, now)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())


def make_mirror(work_dir: Path, clock: Callable[[], str]) -> Callable[[Mapping[str, object]], None]:
    """A mirror callable for :mod:`organize_music.ops.oplog_repo` keyed by ``clock``.

    Returns a function that appends one record per call, using ``clock()`` as the
    timestamp so that as the clock crosses a month the records flow into the new
    file automatically. This is exactly the ``mirror`` argument ``OplogRepo``
    injects: one mapping per successful transition, returning ``None``.
    """

    def mirror(record: Mapping[str, object]) -> None:
        append(work_dir, record, clock())

    return mirror

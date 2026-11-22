"""Library consistency invariants for the crash matrix (PLAN §11, P1-12).

After an op runs and a crash is injected at some step, recovery is run on a
fresh engine and :func:`assert_consistent` checks that nothing was lost or
left in flight:

* the multiset of file-content hashes under ``root`` and every ``extra_dir``
  (the purge folder and the scratch ``tmp/``) still *contains* every hash in
  ``original`` -- content is never destroyed, only moved;
* every ``files`` row whose status is ``'present'`` exists on disk at
  ``root / path`` with the size and ``mtime_ns`` the row records;
* no ``operations`` row is in an in-flight (ACTIVE) state -- the operation
  ended, it did not stall.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

__all__ = ["content_hashes", "assert_consistent"]

_CHUNK = 1 << 20  # 1 MiB, matching the production hashing granularity.

# Operation states that are not terminal: a batch that ends with one of these
# has an operation left in flight and is not consistent at rest (PLAN §5 I5,
# and the operations_one_active_per_file partial index in 0001_initial.sql).
_ACTIVE_STATES: frozenset[str] = frozenset({"intent", "staged", "parked", "applied"})


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def content_hashes(*dirs: Path) -> Counter[str]:
    """The multiset of SHA-256 hashes of every regular file under ``dirs``.

    Directories that do not exist are skipped, so a purge folder or scratch
    directory that was never created contributes nothing.  Symlinks are not
    followed.
    """
    counts: Counter[str] = Counter()
    for directory in dirs:
        path = Path(directory)
        if not path.exists():
            continue
        for entry in path.rglob("*"):
            if entry.is_symlink():
                continue
            if entry.is_file():
                counts[_file_hash(entry)] += 1
    return counts


def assert_consistent(
    root: Path,
    conn: sqlite3.Connection,
    extra_dirs: Sequence[Path],
    original: Counter[str],
) -> None:
    """Assert the library is consistent at rest after a crash and recovery.

    Raises :class:`AssertionError` with a specific reason when any invariant is
    violated, and returns normally when all hold.
    """
    root = Path(root)
    on_disk = content_hashes(root, *extra_dirs)

    # 1. No content was lost: every hash we started with is still present, with
    #    at least its original multiplicity.
    missing = original - on_disk
    if missing:
        raise AssertionError(
            f"content lost after crash/recovery; hashes no longer present on disk: {dict(missing)}"
        )

    # 2. Every 'present' row matches the file on disk by size and mtime_ns.
    rows = conn.execute(
        "SELECT path, size, mtime_ns FROM files WHERE status = 'present'"
    ).fetchall()
    for row in rows:
        rel = row[0]
        expect_size = row[1]
        expect_mtime = row[2]
        target = root / rel
        if not target.is_file():
            raise AssertionError(f"present row {rel!r} has no file on disk at {target}")
        stat = target.stat()
        if stat.st_size != expect_size:
            raise AssertionError(
                f"present row {rel!r} size on disk {stat.st_size} != recorded {expect_size}"
            )
        if stat.st_mtime_ns != expect_mtime:
            raise AssertionError(
                f"present row {rel!r} mtime_ns on disk {stat.st_mtime_ns} != "
                f"recorded {expect_mtime}"
            )

    # 3. No operation is left in flight.
    placeholders = ",".join("?" for _ in _ACTIVE_STATES)
    active = conn.execute(
        f"SELECT op_id, state FROM operations WHERE state IN ({placeholders})",
        tuple(sorted(_ACTIVE_STATES)),
    ).fetchall()
    if active:
        raise AssertionError(
            "operations still in flight after crash/recovery: "
            + ", ".join(f"#{r[0]}({r[1]})" for r in active)
        )

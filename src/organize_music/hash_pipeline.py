"""Resumable MD5 collection over size-collision candidates."""

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from organize_music.dedup import MD5Group, md5_groups, size_collisions
from organize_music.hashing import HashError, md5_file
from organize_music.index_db import IndexDB
from organize_music.models import FileRecord

COMMIT_EVERY = 200
PROGRESS_EVERY = 500
BYTES_PER_MB = 1_000_000


@dataclass(frozen=True)
class HashRun:
    candidates: int
    hashed: int
    cached: int
    failed: int
    pruned: int
    bytes_hashed: int
    failures: tuple[tuple[Path, str], ...]
    groups: tuple[MD5Group, ...]


@dataclass
class _Progress:
    """Mutable counters local to one run (never shared or returned)."""

    hashed: int = 0
    cached: int = 0
    bytes_hashed: int = 0
    started: float = 0.0

    def line(self, index: int, total: int, failed: int) -> str:
        elapsed = max(time.monotonic() - self.started, 1e-9)
        rate = self.bytes_hashed / BYTES_PER_MB / elapsed
        return (
            f"  {index}/{total} (hashed {self.hashed}, cached {self.cached}, "
            f"failed {failed}; {rate:.1f} MB/s)"
        )


def collect_hashes(
    root: Path,
    records: Sequence[FileRecord],
    db: IndexDB,
    say: Callable[[str], None],
    rehash: bool = False,
) -> HashRun:
    """Hash every size-collision candidate, reusing cached MD5s for unchanged files.

    Commits every COMMIT_EVERY files, so an interrupted run resumes where it stopped.
    """
    candidates = size_collisions(records)
    progress = _Progress(started=time.monotonic())
    failures: list[tuple[Path, str]] = []
    hashes: dict[Path, str] = {}
    for index, record in enumerate(candidates, start=1):
        md5 = None if rehash else db.hashes.get(root, record)
        if md5 is not None:
            progress.cached += 1
        else:
            try:
                md5 = md5_file(root / record.path)
            except HashError as exc:
                failures.append((record.path, str(exc)))
            else:
                db.hashes.put(root, record, md5)
                progress.hashed += 1
                progress.bytes_hashed += record.size
        if md5 is not None:
            hashes[record.path] = md5
        if index % COMMIT_EVERY == 0:
            db.commit()
        if index % PROGRESS_EVERY == 0:
            say(progress.line(index, len(candidates), len(failures)))
    pruned = db.hashes.prune(root, set(hashes))
    db.commit()
    return HashRun(
        candidates=len(candidates),
        hashed=progress.hashed,
        cached=progress.cached,
        failed=len(failures),
        pruned=pruned,
        bytes_hashed=progress.bytes_hashed,
        failures=tuple(failures),
        groups=tuple(md5_groups(hashes)),
    )

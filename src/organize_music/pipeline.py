"""Resumable metadata collection: reuse cached raw reads, read only new or changed files."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from organize_music.index_db import IndexDB
from organize_music.metadata import interpret, is_audio
from organize_music.models import FileRecord, ReadFailure, ReadResult, TrackMetadata
from organize_music.tag_reader import TagReadError, read_tags

COMMIT_EVERY = 500
PROGRESS_EVERY = 1000


@dataclass(frozen=True)
class MetaRun:
    tracks: tuple[TrackMetadata, ...]
    read: int
    cached: int
    pruned: int


def read_result(root: Path, record: FileRecord) -> ReadResult:
    """Read one file's tags, turning a parse failure into a ReadFailure."""
    try:
        return read_tags(root / record.path)
    except TagReadError as exc:
        return ReadFailure(error=str(exc))


def collect_metadata(
    root: Path,
    records: Sequence[FileRecord],
    db: IndexDB,
    say: Callable[[str], None],
    rescan: bool = False,
) -> MetaRun:
    """Return metadata for every audio record, reading tags from disk only when needed.

    Cached rows are re-interpreted every run so parser changes apply without re-reading.
    Commits every COMMIT_EVERY files, so an interrupted run resumes where it stopped.
    """
    audio = [r for r in records if is_audio(r)]
    tracks: list[TrackMetadata] = []
    read = cached = 0
    for index, record in enumerate(audio, start=1):
        result = None if rescan else db.get(root, record)
        if result is None:
            result = read_result(root, record)
            read += 1
        else:
            cached += 1
        track = interpret(record, result)
        db.upsert(root, track, result)
        tracks.append(track)
        if index % COMMIT_EVERY == 0:
            db.commit()
        if index % PROGRESS_EVERY == 0:
            say(f"  {index}/{len(audio)} (read {read}, cached {cached})")
    pruned = db.prune(root, {r.path for r in audio})
    db.commit()
    return MetaRun(tracks=tuple(tracks), read=read, cached=cached, pruned=pruned)

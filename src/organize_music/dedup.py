"""Pure duplicate-detection logic. No disk access."""

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path

from organize_music.metadata import is_audio
from organize_music.models import FileRecord

MD5Group = tuple[str, list[Path]]


def size_collisions(records: Sequence[FileRecord]) -> list[FileRecord]:
    """Audio files whose byte size matches another audio file's.

    A file with a unique size cannot be a byte-identical duplicate, so it is never
    hashed. Zero-byte files are read errors, not duplicates, and are excluded.
    """
    audio = [r for r in records if is_audio(r) and r.size > 0]
    sizes = Counter(r.size for r in audio)
    return [r for r in audio if sizes[r.size] > 1]


def md5_groups(hashes: Mapping[Path, str]) -> list[MD5Group]:
    """Groups of 2+ paths sharing an MD5, paths sorted, groups sorted by MD5."""
    by_md5: dict[str, list[Path]] = defaultdict(list)
    for path, md5 in hashes.items():
        by_md5[md5].append(path)
    return sorted((md5, sorted(paths)) for md5, paths in by_md5.items() if len(paths) > 1)

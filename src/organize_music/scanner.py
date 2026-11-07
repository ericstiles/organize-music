"""Read-only walk of the library tree. Never opens files, only stats them."""

import os
from collections.abc import Iterator
from pathlib import Path

from organize_music.models import FileRecord


class LibraryNotFoundError(Exception):
    """The library root is missing, not a directory, or has no files (e.g. not mounted)."""


def _validate_root(root: Path) -> None:
    if not root.exists():
        raise LibraryNotFoundError(f"library root does not exist: {root}")
    if not root.is_dir():
        raise LibraryNotFoundError(f"library root is not a directory: {root}")


def _collect(root: Path) -> list[FileRecord]:
    records: list[FileRecord] = []
    for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            full = Path(dirpath) / name
            stat = full.stat(follow_symlinks=False)
            records.append(
                FileRecord(
                    path=full.relative_to(root),
                    size=stat.st_size,
                    mtime_ns=stat.st_mtime_ns,
                    ext=full.suffix[1:].lower(),
                )
            )
    return records


def single_record(path: Path) -> FileRecord:
    """Build a FileRecord for one file, its path relative to its own parent.

    For reading a lone file (e.g. `tags <file>`) without walking a library.
    """
    if not path.is_file():
        raise LibraryNotFoundError(f"not a file: {path}")
    stat = path.stat(follow_symlinks=False)
    return FileRecord(
        path=Path(path.name),
        size=stat.st_size,
        mtime_ns=stat.st_mtime_ns,
        ext=path.suffix[1:].lower(),
    )


def walk_library(root: Path) -> Iterator[FileRecord]:
    """Yield every file under root, sorted by relative path.

    Raises LibraryNotFoundError before yielding anything if the root is unusable,
    so an unmounted drive fails fast instead of producing an empty report.
    """
    _validate_root(root)
    records = _collect(root)
    if not records:
        raise LibraryNotFoundError(f"library root is empty (is the drive mounted?): {root}")
    yield from sorted(records, key=lambda r: str(r.path))

"""Stat-only scan into the ``files`` table of library.db (PLAN §12).

``scan_into`` walks a library with ``scanner.walk_library`` and, for each record
that ``metadata.is_audio`` accepts, inserts it as kind ``'audio'`` when its
``path_key`` is not already present. The walk is stat-only: nothing is read from
the files, so a scan never interprets tags or art. A single ``commit`` at the end
makes every new row durable. No updates, no missing detection, no tags, no art.
"""

from __future__ import annotations

from pathlib import Path

from organize_music.db.files_repo import FilesRepo
from organize_music.metadata import is_audio
from organize_music.paths import path_key
from organize_music.scanner import walk_library


def scan_into(root: Path, repo: FilesRepo, now: str) -> int:
    """Insert the audio files under ``root`` that are not yet in ``files``.

    Walks ``root`` with :func:`scanner.walk_library` (stat-only). For each record
    that :func:`metadata.is_audio` accepts, whose ``path_key`` is not already
    present, inserts it via :meth:`FilesRepo.insert_scanned` with kind
    ``'audio'``. A single :meth:`FilesRepo.commit` at the end closes the
    transaction. Returns the number of rows inserted.
    """
    inserted = 0
    for record in walk_library(root):
        if not is_audio(record):
            continue
        if repo.get_by_key(path_key(str(record.path))) is not None:
            continue
        repo.insert_scanned(record, "audio", now)
        inserted += 1
    repo.commit()
    return inserted

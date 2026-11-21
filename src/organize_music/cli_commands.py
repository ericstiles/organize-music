"""Subcommand implementations for `organize-music`."""

import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from organize_music.dupes_report import DupesSummary, build_groups, render_duplicates_report
from organize_music.fsops.protocol import write_text_atomic
from organize_music.hash_pipeline import collect_hashes
from organize_music.index_db import IndexDB
from organize_music.metadata import interpret, is_audio
from organize_music.pipeline import collect_metadata, read_all, read_result
from organize_music.reports import ScanSummary, render_metadata_report
from organize_music.scanner import single_record, walk_library
from organize_music.tag_view import render_raw, render_tags

EXIT_OK = 0
BYTES_PER_GB = 1_000_000_000


class UsageError(Exception):
    """Invalid arguments detected before any work starts."""


def _say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _ensure_outside(root: Path, path: Path, what: str) -> None:
    if path.resolve().is_relative_to(root.resolve()):
        raise UsageError(f"{what} must be outside the library: {path}")


def run_meta(
    root: Path, report: Path, index: Path, rescan: bool, skip_folders: frozenset[str]
) -> int:
    root = root.resolve()
    _ensure_outside(root, report, "report")
    _ensure_outside(root, index, "index")
    records = list(walk_library(root))
    _say(f"Found {len(records)} files under {root} (index: {index})")
    with IndexDB.open(index) as db:
        run = collect_metadata(root, records, db, _say, rescan=rescan, skip_folders=skip_folders)
    summary = ScanSummary(
        root=root,
        generated_at=datetime.now(),
        ext_counts=Counter(r.ext for r in records),
        tracks=run.tracks,
    )
    write_text_atomic(report, render_metadata_report(summary))
    errors = sum(1 for t in run.tracks if t.error)
    _say(
        f"{len(run.tracks)} audio files (read {run.read}, cached {run.cached}, "
        f"pruned {run.pruned}, errors {errors}). Report: {report}"
    )
    return EXIT_OK


def run_hash(root: Path, index: Path, rehash: bool) -> int:
    root = root.resolve()
    _ensure_outside(root, index, "index")
    records = list(walk_library(root))
    _say(f"Found {len(records)} files under {root} (index: {index})")
    with IndexDB.open(index) as db:
        run = collect_hashes(root, records, db, _say, rehash=rehash)
    for path, error in run.failures:
        _say(f"  could not hash {path}: {error}")
    _say(
        f"{run.candidates} candidate files (hashed {run.hashed}, cached {run.cached}, "
        f"failed {run.failed}, pruned {run.pruned}); "
        f"{run.bytes_hashed / BYTES_PER_GB:.2f} GB read"
    )
    copies = sum(len(paths) for _md5, paths in run.groups)
    _say(f"{len(run.groups)} groups of byte-identical files ({copies} files)")
    return EXIT_OK


def run_dupes(root: Path, report: Path, index: Path) -> int:
    root = root.resolve()
    _ensure_outside(root, report, "report")
    _ensure_outside(root, index, "index")
    records = list(walk_library(root))
    _say(f"Found {len(records)} files under {root} (index: {index})")
    with IndexDB.open(index) as db:
        run = collect_hashes(root, records, db, _say)
        hashes = db.hashes.all(root)
    sizes = {r.path: r.size for r in records}
    summary = DupesSummary(
        root=root,
        generated_at=datetime.now(),
        candidates=run.candidates,
        groups=build_groups(hashes, sizes),
        failures=run.failures,
    )
    write_text_atomic(report, render_duplicates_report(summary))
    extra = sum(len(g.paths) - 1 for g in summary.groups)
    reclaim = sum(g.reclaimable for g in summary.groups) / BYTES_PER_GB
    _say(
        f"{len(summary.groups)} groups, {extra} extra copies, {reclaim:.2f} GB reclaimable "
        f"(hashed {run.hashed}, cached {run.cached}, failed {run.failed}). Report: {report}"
    )
    return EXIT_OK


def run_tags(path: Path, raw: bool = False) -> int:
    path = path.resolve()
    if path.is_dir():
        root = path
        records = [r for r in walk_library(root) if is_audio(r)]
    elif path.is_file():
        root = path.parent
        records = [single_record(path)]
    else:
        raise UsageError(f"path does not exist: {path}")
    if not records:
        raise UsageError(f"no audio files found: {path}")
    if raw:
        blocks = [render_raw(str(record.path), read_all(root, record)) for record in records]
    else:
        blocks = [render_tags(interpret(record, read_result(root, record))) for record in records]
    print("\n\n".join(blocks))
    return EXIT_OK

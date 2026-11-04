"""Command-line entry point: `organize-music`."""

import argparse
import os
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from organize_music.dupes_report import DupesSummary, build_groups, render_duplicates_report
from organize_music.hash_pipeline import collect_hashes
from organize_music.index_db import IndexDB
from organize_music.pipeline import collect_metadata
from organize_music.reports import ScanSummary, render_metadata_report
from organize_music.scanner import LibraryNotFoundError, walk_library

DEFAULT_REPORT = Path("reports/METADATA_REPORT.md")
DEFAULT_DUPES_REPORT = Path("reports/DUPLICATES_REPORT.md")
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130
BYTES_PER_GB = 1_000_000_000


class UsageError(Exception):
    """Invalid arguments detected before any work starts."""


def default_index_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(data_home) / "organize_music" / "index.db"


def _say(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _ensure_outside(root: Path, path: Path, what: str) -> None:
    if path.resolve().is_relative_to(root.resolve()):
        raise UsageError(f"{what} must be outside the library: {path}")


def run_meta(root: Path, report: Path, index: Path, rescan: bool) -> int:
    root = root.resolve()
    _ensure_outside(root, report, "report")
    _ensure_outside(root, index, "index")
    records = list(walk_library(root))
    _say(f"Found {len(records)} files under {root} (index: {index})")
    with IndexDB.open(index) as db:
        run = collect_metadata(root, records, db, _say, rescan=rescan)
    summary = ScanSummary(
        root=root,
        generated_at=datetime.now(),
        ext_counts=Counter(r.ext for r in records),
        tracks=run.tracks,
    )
    _write_atomic(report, render_metadata_report(summary))
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
    _write_atomic(report, render_duplicates_report(summary))
    extra = sum(len(g.paths) - 1 for g in summary.groups)
    reclaim = sum(g.reclaimable for g in summary.groups) / BYTES_PER_GB
    _say(
        f"{len(summary.groups)} groups, {extra} extra copies, {reclaim:.2f} GB reclaimable "
        f"(hashed {run.hashed}, cached {run.cached}, failed {run.failed}). Report: {report}"
    )
    return EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="organize-music", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    meta = sub.add_parser("meta", help="read tags (read-only) and write a Markdown report")
    meta.add_argument("root", type=Path, help="library root directory")
    meta.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="report path")
    meta.add_argument("--index", type=Path, default=None, help="SQLite index path")
    meta.add_argument("--rescan", action="store_true", help="ignore the index; re-read all tags")
    meta.set_defaults(run=lambda a, index: run_meta(a.root, a.report, index, a.rescan))
    hsh = sub.add_parser("hash", help="MD5 files that share a size (read-only)")
    hsh.add_argument("root", type=Path, help="library root directory")
    hsh.add_argument("--index", type=Path, default=None, help="SQLite index path")
    hsh.add_argument("--rehash", action="store_true", help="ignore cached hashes")
    hsh.set_defaults(run=lambda a, index: run_hash(a.root, index, a.rehash))
    dup = sub.add_parser("dupes", help="report byte-identical files (report only)")
    dup.add_argument("root", type=Path, help="library root directory")
    dup.add_argument("--index", type=Path, default=None, help="SQLite index path")
    dup.add_argument("--report", type=Path, default=DEFAULT_DUPES_REPORT, help="report path")
    dup.set_defaults(run=lambda a, index: run_dupes(a.root, a.report, index))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    index = args.index or default_index_path()
    try:
        return args.run(args, index)
    except (LibraryNotFoundError, UsageError) as exc:
        _say(f"error: {exc}")
        return EXIT_USAGE
    except KeyboardInterrupt:
        _say("interrupted: progress saved to the index; re-run to resume")
        return EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

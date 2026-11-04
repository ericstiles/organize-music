"""Command-line entry point: `organize-music`."""

import argparse
import os
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from organize_music.index_db import IndexDB
from organize_music.pipeline import collect_metadata
from organize_music.reports import ScanSummary, render_metadata_report
from organize_music.scanner import LibraryNotFoundError, walk_library

DEFAULT_REPORT = Path("reports/METADATA_REPORT.md")
EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="organize-music", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    meta = sub.add_parser("meta", help="read tags (read-only) and write a Markdown report")
    meta.add_argument("root", type=Path, help="library root directory")
    meta.add_argument("--report", type=Path, default=DEFAULT_REPORT, help="report path")
    meta.add_argument("--index", type=Path, default=None, help="SQLite index path")
    meta.add_argument("--rescan", action="store_true", help="ignore the index; re-read all tags")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    index = args.index or default_index_path()
    try:
        return run_meta(args.root, args.report, index, args.rescan)
    except (LibraryNotFoundError, UsageError) as exc:
        _say(f"error: {exc}")
        return EXIT_USAGE
    except KeyboardInterrupt:
        _say("interrupted: progress saved to the index; re-run to resume")
        return EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

"""Command-line entry point: `organize-music`."""

import argparse
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from organize_music.config import Config, ConfigError, load_config
from organize_music.dupes_report import DupesSummary, build_groups, render_duplicates_report
from organize_music.hash_pipeline import collect_hashes
from organize_music.index_db import IndexDB
from organize_music.metadata import interpret, is_audio
from organize_music.pipeline import collect_metadata, read_all, read_result
from organize_music.reports import ScanSummary, render_metadata_report
from organize_music.scanner import LibraryNotFoundError, single_record, walk_library
from organize_music.tag_view import render_raw, render_tags

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130
BYTES_PER_GB = 1_000_000_000


class UsageError(Exception):
    """Invalid arguments detected before any work starts."""


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


def _root(args: argparse.Namespace, config: Config) -> Path:
    return args.root or config.library


def _report(args: argparse.Namespace, config: Config, filename: str) -> Path:
    return args.report or config.reports / filename


def _index(args: argparse.Namespace, config: Config) -> Path:
    return args.index or config.index


def _add_common(subparser: argparse.ArgumentParser, *, report_name: str | None = None) -> None:
    subparser.add_argument("root", type=Path, nargs="?", default=None, help="library root")
    subparser.add_argument("--config", type=Path, default=None, help="YAML config file")
    subparser.add_argument("--index", type=Path, default=None, help="SQLite index path")
    if report_name is not None:
        subparser.add_argument("--report", type=Path, default=None, help="report path")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="organize-music", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    meta = sub.add_parser("meta", help="read tags (read-only) and write a Markdown report")
    _add_common(meta, report_name="METADATA_REPORT.md")
    meta.add_argument("--rescan", action="store_true", help="ignore the index; re-read all tags")
    meta.set_defaults(
        run=lambda a, c: run_meta(
            _root(a, c), _report(a, c, "METADATA_REPORT.md"), _index(a, c), a.rescan
        )
    )

    hsh = sub.add_parser("hash", help="MD5 files that share a size (read-only)")
    _add_common(hsh)
    hsh.add_argument("--rehash", action="store_true", help="ignore cached hashes")
    hsh.set_defaults(run=lambda a, c: run_hash(_root(a, c), _index(a, c), a.rehash))

    dup = sub.add_parser("dupes", help="report byte-identical files (report only)")
    _add_common(dup, report_name="DUPLICATES_REPORT.md")
    dup.set_defaults(
        run=lambda a, c: run_dupes(_root(a, c), _report(a, c, "DUPLICATES_REPORT.md"), _index(a, c))
    )

    tags = sub.add_parser("tags", help="print tag values for a file or directory to stdout")
    tags.add_argument("path", type=Path, help="an audio file, or a directory to scan")
    tags.add_argument("--config", type=Path, default=None, help="YAML config file")
    tags.add_argument("--raw", action="store_true", help="dump every stored tag, uninterpreted")
    tags.set_defaults(run=lambda a, c: run_tags(a.path, a.raw))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = load_config(args.config)
        return args.run(args, config)
    except (LibraryNotFoundError, UsageError, ConfigError) as exc:
        _say(f"error: {exc}")
        return EXIT_USAGE
    except KeyboardInterrupt:
        _say("interrupted: progress saved to the index; re-run to resume")
        return EXIT_INTERRUPTED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

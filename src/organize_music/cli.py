"""Command-line entry point: `organize-music`."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from organize_music.cli_commands import (
    UsageError,
    _say,
    run_dupes,
    run_hash,
    run_meta,
    run_tags,
)
from organize_music.cli_serve import run_recover, run_serve
from organize_music.config import Config, ConfigError, load_config
from organize_music.scanner import LibraryNotFoundError

EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


def _root(args: argparse.Namespace, config: Config) -> Path:
    root = args.root or config.library
    if root is None:
        raise UsageError(
            "no library: pass a root, set 'library' in the config, or export MUSIC_LIB"
        )
    return root


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
            _root(a, c),
            _report(a, c, "METADATA_REPORT.md"),
            _index(a, c),
            a.rescan,
            frozenset(c.skip_folders),
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

    serve = sub.add_parser(
        "serve", help="run the web server (takes the writer lock for its lifetime)"
    )
    serve.add_argument("--config", type=Path, default=None, help="YAML config file")
    serve.set_defaults(run=lambda a, c: run_serve(c))

    rec = sub.add_parser("recover", help="recover interrupted operations and exit")
    rec.add_argument("--config", type=Path, default=None, help="YAML config file")
    rec.set_defaults(run=lambda a, c: run_recover(c))
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

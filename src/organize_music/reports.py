"""Pure rendering of scan results into Markdown. No disk access."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from organize_music.models import FIELD_NAMES, Source, TrackMetadata

SAMPLE_LIMIT = 50
TOP_FOLDERS = 15
NONE_LINE = "_None._"


@dataclass(frozen=True)
class ScanSummary:
    root: Path
    generated_at: datetime
    ext_counts: Mapping[str, int]
    tracks: Sequence[TrackMetadata]


def _cell(text: object) -> str:
    """Make text safe inside a Markdown table cell."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _code(path: Path) -> str:
    return f"`{_cell(path)}`"


def _is_untagged(track: TrackMetadata) -> bool:
    return track.error is None and (
        track.artist.source is Source.MISSING or track.title.source is Source.MISSING
    )


def _totals(summary: ScanSummary) -> list[str]:
    errors = sum(1 for t in summary.tracks if t.error)
    return [
        "## Totals",
        "",
        "| Measure | Count |",
        "|---------|------:|",
        f"| Files scanned | {sum(summary.ext_counts.values())} |",
        f"| Audio files read | {len(summary.tracks)} |",
        f"| Read errors | {errors} |",
        f"| Missing artist or title | {sum(1 for t in summary.tracks if _is_untagged(t))} |",
    ]


def _extensions(summary: ScanSummary) -> list[str]:
    rows = sorted(summary.ext_counts.items(), key=lambda kv: (-kv[1], kv[0]))
    lines = ["## Files by extension", "", "| Extension | Count |", "|-----------|------:|"]
    return lines + [f"| {_cell(ext or '(none)')} | {count} |" for ext, count in rows]


def _coverage(summary: ScanSummary) -> list[str]:
    readable = [t for t in summary.tracks if t.error is None]
    lines = [
        "## Field coverage",
        "",
        f"Where each field came from, across the {len(readable)} readable audio files.",
        "Share is the share set by tags alone.",
        "",
        "| Field | From tag | Share | From filename | From folder | Missing |",
        "|-------|---------:|------:|--------------:|------------:|--------:|",
    ]
    for name in FIELD_NAMES:
        counts = Counter(getattr(t, name).source for t in readable)
        share = 100 * counts[Source.TAG] / len(readable) if readable else 0.0
        lines.append(
            f"| {name} | {counts[Source.TAG]} | {share:.1f}% | {counts[Source.FILENAME]} "
            f"| {counts[Source.FOLDER]} | {counts[Source.MISSING]} |"
        )
    return lines


def _errors(summary: ScanSummary) -> list[str]:
    failed = [t for t in summary.tracks if t.error]
    lines = ["## Read errors", ""]
    if not failed:
        return [*lines, NONE_LINE]
    lines += ["| File | Error |", "|------|-------|"]
    return lines + [f"| {_code(t.record.path)} | {_cell(t.error)} |" for t in failed]


def _untagged_folders(summary: ScanSummary) -> list[str]:
    counts = Counter(t.record.path.parent for t in summary.tracks if _is_untagged(t))
    lines = ["## Folders with the most files missing artist or title", ""]
    if not counts:
        return [*lines, NONE_LINE]
    lines += ["| Folder | Files |", "|--------|------:|"]
    return lines + [f"| {_code(p)} | {n} |" for p, n in counts.most_common(TOP_FOLDERS)]


def _untagged_sample(summary: ScanSummary) -> list[str]:
    untagged = [t for t in summary.tracks if _is_untagged(t)]
    lines = [f"## Sample of files missing artist or title (first {SAMPLE_LIMIT})", ""]
    if not untagged:
        return [*lines, NONE_LINE]
    return lines + [f"- {_code(t.record.path)}" for t in untagged[:SAMPLE_LIMIT]]


def render_metadata_report(summary: ScanSummary) -> str:
    """Render the full METADATA_REPORT.md text."""
    header = [
        "# Metadata Report",
        "",
        f"- Library: `{summary.root}`",
        f"- Generated: {summary.generated_at:%Y-%m-%d %H:%M}",
        "- Read-only run: no files were changed.",
    ]
    sections = [
        header,
        _totals(summary),
        _extensions(summary),
        _coverage(summary),
        _errors(summary),
        _untagged_folders(summary),
        _untagged_sample(summary),
    ]
    return "\n\n".join("\n".join(s) for s in sections) + "\n"

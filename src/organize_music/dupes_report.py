"""Pure duplicate grouping and DUPLICATES_REPORT.md rendering. No disk access.

Report only: no keeper is chosen (see docs/PLAN.md, Phase 3).
"""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import combinations
from pathlib import Path

from organize_music.dedup import md5_groups
from organize_music.markdown import NONE_LINE, cell, code

GROUP_LIMIT = 200
PAIR_LIMIT = 25
ROOT_LABEL = "(library root)"
BYTES_PER_MB = 1_000_000
BYTES_PER_GB = 1_000_000_000


@dataclass(frozen=True)
class DupGroup:
    md5: str
    size: int
    paths: tuple[Path, ...]

    @property
    def reclaimable(self) -> int:
        return self.size * (len(self.paths) - 1)


@dataclass(frozen=True)
class DupesSummary:
    root: Path
    generated_at: datetime
    candidates: int
    groups: tuple[DupGroup, ...]
    failures: tuple[tuple[Path, str], ...]


def build_groups(hashes: Mapping[Path, str], sizes: Mapping[Path, int]) -> tuple[DupGroup, ...]:
    """Byte-identical groups, largest reclaimable space first."""
    groups = [
        DupGroup(md5=md5, size=sizes[paths[0]], paths=tuple(paths))
        for md5, paths in md5_groups(hashes)
    ]
    return tuple(sorted(groups, key=lambda g: (-g.reclaimable, g.md5)))


def _top_folder(path: Path) -> str:
    return path.parts[0] if len(path.parts) > 1 else ROOT_LABEL


def _totals(summary: DupesSummary) -> list[str]:
    files = sum(len(g.paths) for g in summary.groups)
    reclaim = sum(g.reclaimable for g in summary.groups)
    return [
        "## Totals",
        "",
        "| Measure | Value |",
        "|---------|------:|",
        f"| Size-collision candidates hashed | {summary.candidates} |",
        f"| Groups of byte-identical files | {len(summary.groups)} |",
        f"| Files in those groups | {files} |",
        f"| Extra copies (files beyond one per group) | {files - len(summary.groups)} |",
        f"| Reclaimable space | {reclaim / BYTES_PER_GB:.2f} GB |",
        f"| Files that could not be hashed | {len(summary.failures)} |",
    ]


def _overlap(summary: DupesSummary) -> list[str]:
    pairs: Counter[tuple[str, str]] = Counter()
    for group in summary.groups:
        folders = sorted({_top_folder(p) for p in group.paths})
        pairs.update(combinations(folders, 2))
    lines = [
        "## Top-level folders sharing duplicates",
        "",
        "Number of duplicate groups with copies in both folders.",
        "",
    ]
    if not pairs:
        return [*lines, NONE_LINE]
    lines += ["| Folders | Groups |", "|---------|-------:|"]
    ranked = sorted(pairs.items(), key=lambda kv: (-kv[1], kv[0]))[:PAIR_LIMIT]
    return lines + [f"| {code(a)} ↔ {code(b)} | {n} |" for (a, b), n in ranked]


def _groups(summary: DupesSummary) -> list[str]:
    lines = ["## Duplicate groups (largest reclaimable space first)", ""]
    if not summary.groups:
        return [*lines, NONE_LINE]
    shown = summary.groups[:GROUP_LIMIT]
    if len(shown) < len(summary.groups):
        lines += [f"Showing the largest {len(shown)} of {len(summary.groups)} groups.", ""]
    for number, group in enumerate(shown, start=1):
        size_mb = group.size / BYTES_PER_MB
        lines.append(
            f"### {number}. {len(group.paths)} copies × {size_mb:.1f} MB (md5 `{group.md5}`)"
        )
        lines += ["", *[f"- {code(p)}" for p in group.paths], ""]
    return lines[:-1]


def _failures(summary: DupesSummary) -> list[str]:
    lines = ["## Files that could not be hashed", ""]
    if not summary.failures:
        return [*lines, NONE_LINE]
    lines += ["| File | Error |", "|------|-------|"]
    return lines + [f"| {code(p)} | {cell(e)} |" for p, e in summary.failures]


def render_duplicates_report(summary: DupesSummary) -> str:
    header = [
        "# Duplicates Report",
        "",
        f"- Library: `{summary.root}`",
        f"- Generated: {summary.generated_at:%Y-%m-%d %H:%M}",
        "- Report only: no keeper is chosen and no files were moved.",
        "- Byte-identical = same MD5. Same song with different tags is not detected yet.",
    ]
    sections: Sequence[list[str]] = [
        header,
        _totals(summary),
        _overlap(summary),
        _groups(summary),
        _failures(summary),
    ]
    return "\n\n".join("\n".join(s) for s in sections) + "\n"

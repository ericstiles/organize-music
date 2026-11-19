"""Enforce the repo's 200-line-per-file limit (CLAUDE.md guardrail 1)."""

import pathlib

from organize_music import __file__ as package_file

SRC = pathlib.Path(package_file).parent
LIMIT = 200


def test_every_source_file_stays_under_the_line_limit() -> None:
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        lines = len(path.read_text(encoding="utf-8").splitlines())
        if lines > LIMIT:
            offenders.append((path.relative_to(SRC.parent), lines))
    assert not offenders, (
        f"{len(offenders)} source file(s) exceed the {LIMIT}-line limit:\n"
        + "\n".join(f"  {rel}: {lines} lines" for rel, lines in offenders)
    )

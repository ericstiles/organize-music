"""The reviewer's verdict: parse it, add gate results, render comments and debt issues (pure)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

MARKER_PREFIX = "pr-review:"
DEBT_LABEL = "tech-debt"
_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_PATH_LINE = re.compile(r"^(?P<path>[^:\s]+):(?P<line>\d+):")


@dataclass(frozen=True)
class Problem:
    file: str
    line: int | None
    title: str
    detail: str

    def location(self) -> str:
        return self.file if self.line is None else f"{self.file}:{self.line}"


@dataclass(frozen=True)
class Verdict:
    approve: bool
    summary: str
    problems: tuple[Problem, ...]


def _payload(raw: str) -> dict[str, object]:
    envelope = json.loads(raw)
    structured = envelope.get("structured_output")
    if isinstance(structured, dict):
        return structured
    text = str(envelope.get("result", "")).strip()
    fenced = _FENCE.search(text)
    try:
        payload = json.loads(fenced.group(1) if fenced else text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"reviewer did not return a JSON verdict: {text[:200]!r}") from exc
    if not isinstance(payload, dict):
        raise ValueError("reviewer verdict is not a JSON object")
    return payload


def parse_verdict(raw: str) -> Verdict:
    """Parse `claude -p --output-format json` output into a Verdict."""
    payload = _payload(raw)
    problems = tuple(
        Problem(
            file=str(p.get("file", "")),
            line=int(p["line"]) if p.get("line") not in (None, "") else None,
            title=str(p.get("title", "")).strip(),
            detail=str(p.get("detail", "")).strip(),
        )
        for p in payload.get("problems", [])  # type: ignore[union-attr]
    )
    approve = bool(payload.get("approve")) and not problems
    return Verdict(approve, str(payload.get("summary", "")).strip(), problems)


def with_checks(
    verdict: Verdict, failures: list[str], ruff: list[str], unformatted: list[str]
) -> Verdict:
    """Add mechanical gate regressions as problems; any of them blocks approval."""
    found = [Problem(n.split("::")[0], None, f"New test failure: {n}", "") for n in failures]
    for line in ruff:
        match = _PATH_LINE.match(line)
        path, number = (match["path"], int(match["line"])) if match else ("", None)
        message = line.split(": ", 1)[1] if ": " in line else line
        found.append(Problem(path, number, f"New ruff finding: {message}", ""))
    found += [Problem(p, None, "File not formatted", "ruff format --check") for p in unformatted]
    if not found:
        return verdict
    return replace(verdict, approve=False, problems=verdict.problems + tuple(found))


def review_comment(verdict: Verdict, head_sha: str) -> str:
    """Markdown review comment; the hidden marker records which head commit was reviewed."""
    status = "Approved and merged" if verdict.approve else "Changes needed, not merged"
    lines = [f"<!-- {MARKER_PREFIX}{head_sha} -->", f"**Reviewer agent: {status}**", ""]
    lines.append(verdict.summary or "(no summary)")
    if verdict.problems:
        lines += ["", "Problems:"]
        for p in verdict.problems:
            suffix = f": {p.detail}" if p.detail else ""
            lines.append(f"- `{p.location()}` {p.title}{suffix}")
    return "\n".join(lines) + "\n"


def debt_issue_args(problem: Problem, bead: str, pr: int) -> list[str]:
    """`bd` arguments that file one tech-debt issue for a review problem."""
    body = (
        f"## Problem\n{problem.title}\n\nWhere: `{problem.location()}`\n\n{problem.detail}\n\n"
        f"Found by the reviewer agent on PR #{pr} for {bead}.\n\n"
        "## Fix scope\nOnly what is needed to resolve the problem above.\n\n"
        "## Base branch\n`main`\n\n"
        "## Tests first\nWrite a test that fails on the current code for the reason above.\n\n"
        "## Constraints\nPython >= 3.12, quality gate "
        "`ruff check . && ruff format --check . && pytest`, conventional commits.\n"
    )
    return [
        "create",
        f"Tech debt from PR #{pr}: {problem.title}"[:200],
        "-t",
        "bug",
        "-p",
        "2",
        "-l",
        DEBT_LABEL,
        "--deps",
        f"discovered-from:{bead}",
        "-d",
        body,
        "--silent",
    ]

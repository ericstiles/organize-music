"""Compare quality-gate output on a PR with `main` and keep only what is new (pure)."""

from __future__ import annotations

import re
from collections import Counter

# ruff --output-format concise: "path:line:col: CODE message"
_RUFF = re.compile(r"^(?P<path>[^:\s]+):\d+:\d+: (?P<rest>[A-Z]+\d+ .*)$")
# pytest -q summary: "FAILED nodeid - reason" / "ERROR nodeid - reason"
_PYTEST = re.compile(r"^(?:FAILED|ERROR) (?P<node>\S+)")
# ruff format --check: "Would reformat: path" (older) or, with --output-format concise,
# "path:line:col: unformatted: File would be reformatted"
_FORMAT = re.compile(r"^(?:Would reformat: (?P<old>\S+)|(?P<new>[^:\s]+):\d+:\d+: unformatted:.*)$")


def _ruff_keys(text: str) -> list[tuple[tuple[str, str], str]]:
    """(path, code+message) keys with the original line; line numbers are ignored."""
    out = []
    for line in text.splitlines():
        match = _RUFF.match(line.strip())
        if match:
            out.append(((match["path"], match["rest"]), line.strip()))
    return out


def new_ruff_findings(main_text: str, pr_text: str) -> list[str]:
    """Ruff findings on the PR that `main` does not have (same file and message, any line)."""
    budget = Counter(key for key, _ in _ruff_keys(main_text))
    new = []
    for key, line in _ruff_keys(pr_text):
        if budget[key] > 0:
            budget[key] -= 1
        else:
            new.append(line)
    return new


def _matches(pattern: re.Pattern[str], groups: tuple[str, ...], text: str) -> list[str]:
    found: list[str] = []
    for line in text.splitlines():
        match = pattern.match(line.strip())
        value = next((match[g] for g in groups if match[g]), None) if match else None
        if value and value not in found:
            found.append(value)
    return found


def new_failures(main_text: str, pr_text: str) -> list[str]:
    """Test node ids that fail or error on the PR but not on `main`."""
    old = set(_matches(_PYTEST, ("node",), main_text))
    return [node for node in _matches(_PYTEST, ("node",), pr_text) if node not in old]


def new_unformatted(main_text: str, pr_text: str) -> list[str]:
    """Files `ruff format --check` would reformat on the PR but not on `main`."""
    groups = ("old", "new")
    old = set(_matches(_FORMAT, groups, main_text))
    return [path for path in _matches(_FORMAT, groups, pr_text) if path not in old]

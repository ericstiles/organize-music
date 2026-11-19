"""Ask a headless Claude reviewer for a verdict on one PR (read-only tools only)."""

from __future__ import annotations

import json
from pathlib import Path

from tools.pr_review.shell import Runner, must

AGENT_TIMEOUT = 1500.0
READ_ONLY_TOOLS = "Read,Grep,Glob,Bash(git diff:*),Bash(git log:*),Bash(git show:*)"
VERDICT_SCHEMA = {
    "type": "object",
    "required": ["approve", "summary", "problems"],
    "properties": {
        "approve": {"type": "boolean"},
        "summary": {"type": "string"},
        "problems": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["file", "title", "detail"],
                "properties": {
                    "file": {"type": "string"},
                    "line": {"type": ["integer", "null"]},
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                },
            },
        },
    },
}


def build_prompt(instructions: str, ticket: str, pr_body: str, diff: str, checks: str) -> str:
    return "\n\n".join(
        [
            instructions.strip(),
            "## Ticket (bd show)\n" + ticket.strip(),
            "## PR description\n" + pr_body.strip(),
            "## Mechanical gate results (PR rebased on main, compared with main)\n"
            + checks.strip(),
            "## Diff against origin/main\n```diff\n" + diff.strip() + "\n```",
        ]
    )


def ask(run: Runner, tree: Path, prompt: str, model: str | None) -> str:
    """Run `claude -p` in the PR worktree and return its JSON output."""
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--json-schema", json.dumps(VERDICT_SCHEMA),
        "--allowedTools", READ_ONLY_TOOLS,
        "--disallowedTools", "Edit,Write,NotebookEdit,WebFetch,WebSearch",
    ]  # fmt: skip
    if model:
        cmd += ["--model", model]
    return must(run(cmd, cwd=tree, timeout=AGENT_TIMEOUT), "claude reviewer").out

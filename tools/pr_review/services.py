"""GitHub (gh) and beads (bd) calls used by the reviewer agent."""

from __future__ import annotations

import json
from dataclasses import dataclass

from tools.pr_review.meta import BRANCH_PREFIX
from tools.pr_review.shell import Runner, must
from tools.pr_review.verdict import MARKER_PREFIX

_PR_FIELDS = "number,title,body,headRefName,headRefOid,url,isDraft"


@dataclass(frozen=True)
class PullRequest:
    number: int
    title: str
    body: str
    branch: str
    head_sha: str
    url: str


class GitHub:
    def __init__(self, run: Runner, reviewer_token: str | None = None) -> None:
        self._run = run
        self._token = reviewer_token

    def open_bead_prs(self) -> list[PullRequest]:
        """Open, non-draft PRs whose branch is bd/<id>, oldest first."""
        cmd = ["gh", "pr", "list", "--state", "open", "--limit", "50", "--json", _PR_FIELDS]
        rows = json.loads(must(self._run(cmd), "gh pr list").out or "[]")
        prs = [
            PullRequest(
                r["number"],
                r["title"],
                r["body"] or "",
                r["headRefName"],
                r["headRefOid"],
                r["url"],
            )
            for r in rows
            if r["headRefName"].startswith(BRANCH_PREFIX) and not r.get("isDraft")
        ]
        return sorted(prs, key=lambda p: p.number)

    def already_reviewed(self, pr: PullRequest) -> bool:
        """True when a reviewer-agent comment already covers this head commit."""
        cmd = ["gh", "pr", "view", str(pr.number), "--json", "comments,reviews"]
        data = json.loads(must(self._run(cmd), "gh pr view").out)
        marker = f"<!-- {MARKER_PREFIX}{pr.head_sha} -->"
        bodies = [c.get("body", "") for c in data.get("comments", []) + data.get("reviews", [])]
        return any(marker in body for body in bodies)

    def post_review(self, pr: PullRequest, text: str, approve: bool) -> None:
        """Approve / request changes with the reviewer identity, else post a comment."""
        if self._token:
            flag = "--approve" if approve else "--request-changes"
            cmd = ["gh", "pr", "review", str(pr.number), flag, "--body", text]
            must(self._run(cmd, env={"GH_TOKEN": self._token}), "gh pr review")
            return
        cmd = ["gh", "pr", "comment", str(pr.number), "--body", text]
        must(self._run(cmd), "gh pr comment")

    def merge(self, pr: PullRequest) -> None:
        cmd = [
            "gh",
            "pr",
            "merge",
            str(pr.number),
            "--rebase",
            "--delete-branch",
            "--match-head-commit",
            pr.head_sha,
        ]
        must(self._run(cmd), "gh pr merge")


class Beads:
    def __init__(self, run: Runner) -> None:
        self._run = run

    def pull(self) -> None:
        must(self._run(["bd", "dolt", "pull"]), "bd dolt pull")

    def show(self, bead: str) -> dict[str, object]:
        data = json.loads(must(self._run(["bd", "show", bead, "--json"]), "bd show").out)
        return data[0] if isinstance(data, list) else data

    def text(self, bead: str) -> str:
        return must(self._run(["bd", "show", bead]), "bd show").out

    def close(self, bead: str, pr: PullRequest) -> None:
        cmd = ["bd", "close", bead, "--force", "--reason", f"merged PR #{pr.number}", "--json"]
        must(self._run(cmd), "bd close")

    def note(self, bead: str, text: str) -> None:
        must(self._run(["bd", "update", bead, "--append-notes", text]), "bd update")

    def create(self, args: list[str]) -> str:
        return must(self._run(["bd", *args]), "bd create").out.strip()

    def push(self) -> None:
        """Push beads; on a rejected push (someone else pushed), pull once and retry."""
        if self._run(["bd", "dolt", "push"]).ok:
            return
        self.pull()
        must(self._run(["bd", "dolt", "push"]), "bd dolt push")

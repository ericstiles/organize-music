"""Decision flow of the PR reviewer agent with fake GitHub and beads services."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.pr_review import review
from tools.pr_review.services import PullRequest
from tools.pr_review.verdict import Problem, Verdict

URL = "https://github.com/o/r/pull/7"
PR = PullRequest(7, "fix(om-1): thing", "Bead: om-1", "bd/om-1", "sha7", URL)


class FakeGitHub:
    def __init__(self, reviewed: bool = False) -> None:
        self.reviewed = reviewed
        self.calls: list[tuple[str, object]] = []

    def already_reviewed(self, pr: PullRequest) -> bool:
        return self.reviewed

    def post_review(self, pr: PullRequest, text: str, approve: bool) -> None:
        self.calls.append(("review", approve))

    def merge(self, pr: PullRequest) -> None:
        self.calls.append(("merge", pr.number))


class FakeBeads:
    def __init__(self, status: str = "in_progress", notes: str = f"PR: {URL}") -> None:
        self.info = {"status": status, "notes": notes}
        self.calls: list[tuple[str, object]] = []

    def show(self, bead: str) -> dict[str, object]:
        return self.info

    def close(self, bead: str, pr: PullRequest) -> None:
        self.calls.append(("close", bead))

    def create(self, args: list[str]) -> str:
        self.calls.append(("create", args[1]))
        return f"om-new{len(self.calls)}"

    def note(self, bead: str, text: str) -> None:
        self.calls.append(("note", bead))

    def push(self) -> None:
        self.calls.append(("push", None))


def _ctx(gh: FakeGitHub, bd: FakeBeads, dry_run: bool = False) -> review.Context:
    return review.Context(run=None, repo=Path("."), github=gh, beads=bd, dry_run=dry_run)  # type: ignore[arg-type]


@pytest.fixture
def verdict(monkeypatch: pytest.MonkeyPatch) -> list[Verdict]:
    holder = [Verdict(True, "ok", ())]
    monkeypatch.setattr(review, "fetch", lambda run, repo, number: "ref")
    monkeypatch.setattr(review, "_verdict", lambda ctx, pr, bead, ref: holder[0])
    return holder


def test_good_pr_is_approved_merged_and_closed(verdict: list[Verdict]) -> None:
    gh, bd = FakeGitHub(), FakeBeads()
    assert review.review_pr(_ctx(gh, bd), PR) == "merged"
    assert gh.calls == [("review", True), ("merge", 7)]
    assert bd.calls == [("close", "om-1"), ("push", None)]


def test_bad_pr_files_one_debt_issue_per_problem_and_is_not_merged(
    verdict: list[Verdict],
) -> None:
    verdict[0] = Verdict(False, "no", (Problem("a.py", 1, "A", ""), Problem("b.py", 2, "B", "")))
    gh, bd = FakeGitHub(), FakeBeads()
    assert review.review_pr(_ctx(gh, bd), PR) == "changes-needed"
    assert gh.calls == [("review", False)]
    assert [c[0] for c in bd.calls] == ["create", "create", "note", "push"]


def test_dry_run_changes_nothing(verdict: list[Verdict]) -> None:
    gh, bd = FakeGitHub(), FakeBeads()
    assert review.review_pr(_ctx(gh, bd, dry_run=True), PR) == "merged"
    assert gh.calls == [] and bd.calls == []


def test_mismatched_bead_is_refused_with_a_comment(verdict: list[Verdict]) -> None:
    gh, bd = FakeGitHub(), FakeBeads()
    bad = PullRequest(8, "fix(om-2): x", "Bead: om-1", "bd/om-1", "sha8", URL)
    assert review.review_pr(_ctx(gh, bd), bad) == "refused"
    assert gh.calls == [("review", False)] and bd.calls == []


@pytest.mark.parametrize(("status", "notes"), [("closed", f"PR: {URL}"), ("in_progress", "")])
def test_bead_must_be_in_progress_with_pr_link(
    verdict: list[Verdict], status: str, notes: str
) -> None:
    gh, bd = FakeGitHub(), FakeBeads(status, notes)
    assert review.review_pr(_ctx(gh, bd), PR) == "refused"
    assert ("merge", 7) not in gh.calls


def test_already_reviewed_head_is_skipped(verdict: list[Verdict]) -> None:
    gh, bd = FakeGitHub(reviewed=True), FakeBeads()
    assert review.review_pr(_ctx(gh, bd), PR) == "skipped"
    assert gh.calls == [] and bd.calls == []

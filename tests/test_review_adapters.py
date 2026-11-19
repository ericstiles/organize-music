"""gh / bd / git / claude adapters of the reviewer agent, driven by a recording fake runner."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

from tools.pr_review import __main__ as cli
from tools.pr_review import agent, gate
from tools.pr_review.services import Beads, GitHub, PullRequest
from tools.pr_review.shell import CommandError, Result, run

PR = PullRequest(7, "fix(om-1): t", "Bead: om-1", "bd/om-1", "sha7", "u")
Reply = Callable[[list[str]], Result]


class FakeRun:
    def __init__(self, reply: Reply | None = None) -> None:
        self.reply = reply or (lambda cmd: Result(0, "", ""))
        self.calls: list[tuple[list[str], Mapping[str, str] | None]] = []

    def __call__(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Result:
        self.calls.append((list(cmd), env))
        return self.reply(list(cmd))

    def cmds(self) -> list[str]:
        return [" ".join(c[:4]) for c, _ in self.calls]


def test_run_captures_output_and_missing_command() -> None:
    assert run([sys.executable, "-c", "print('hi')"]).out == "hi\n"
    assert run([sys.executable, "-c", "import sys; sys.exit(3)"]).code == 3
    assert run(["definitely-not-a-command-xyz"]).code == 127


def test_run_timeout_is_exit_124() -> None:
    assert run([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.2).code == 124


def test_open_bead_prs_filters_branch_and_drafts() -> None:
    rows = [
        {"number": 9, "title": "t", "body": None, "headRefName": "bd/om-2", "headRefOid": "b",
         "url": "u9", "isDraft": False},
        {"number": 3, "title": "t", "body": "x", "headRefName": "bd/om-1", "headRefOid": "a",
         "url": "u3", "isDraft": False},
        {"number": 4, "title": "t", "body": "", "headRefName": "feature/x", "headRefOid": "c",
         "url": "u4", "isDraft": False},
        {"number": 5, "title": "t", "body": "", "headRefName": "bd/om-5", "headRefOid": "d",
         "url": "u5", "isDraft": True},
    ]  # fmt: skip
    fake = FakeRun(lambda cmd: Result(0, json.dumps(rows), ""))
    assert [p.number for p in GitHub(fake).open_bead_prs()] == [3, 9]


def test_already_reviewed_looks_for_head_marker() -> None:
    data = {"comments": [{"body": "<!-- pr-review:sha7 -->\nok"}], "reviews": []}
    assert GitHub(FakeRun(lambda cmd: Result(0, json.dumps(data), ""))).already_reviewed(PR)
    other = {"comments": [{"body": "<!-- pr-review:old -->"}], "reviews": []}
    assert not GitHub(FakeRun(lambda cmd: Result(0, json.dumps(other), ""))).already_reviewed(PR)


def test_review_uses_reviewer_token_to_approve_else_comments() -> None:
    fake = FakeRun()
    GitHub(fake, "tok").post_review(PR, "body", approve=True)
    GitHub(fake, "tok").post_review(PR, "body", approve=False)
    GitHub(fake).post_review(PR, "body", approve=True)
    assert [c[0][3:5] for c in fake.calls[:2]] == [["7", "--approve"], ["7", "--request-changes"]]
    assert fake.calls[0][1] == {"GH_TOKEN": "tok"}
    assert fake.calls[2][0][:3] == ["gh", "pr", "comment"] and fake.calls[2][1] is None


def test_merge_pins_the_reviewed_head() -> None:
    fake = FakeRun()
    GitHub(fake).merge(PR)
    assert fake.calls[0][0][-2:] == ["--match-head-commit", "sha7"]
    assert "--rebase" in fake.calls[0][0]


def test_failed_command_raises() -> None:
    with pytest.raises(CommandError, match="gh pr merge"):
        GitHub(FakeRun(lambda cmd: Result(1, "", "boom"))).merge(PR)


def test_beads_calls() -> None:
    fake = FakeRun(lambda cmd: Result(0, json.dumps([{"status": "open"}]), ""))
    beads = Beads(fake)
    assert beads.show("om-1") == {"status": "open"}
    beads.text("om-1")
    beads.close("om-1", PR)
    beads.note("om-1", "n")
    beads.create(["create", "x"])
    assert fake.cmds() == [
        "bd show om-1 --json", "bd show om-1", "bd close om-1 --force",
        "bd update om-1 --append-notes", "bd create x",
    ]  # fmt: skip


def test_beads_push_pulls_and_retries_once_after_rejection() -> None:
    pushes = iter([Result(1, "", "rejected"), Result(0, "", "")])
    fake = FakeRun(lambda cmd: next(pushes) if cmd[2] == "push" else Result(0, "", ""))
    Beads(fake).push()
    assert fake.cmds() == ["bd dolt push", "bd dolt pull", "bd dolt push"]


def test_gate_runs_three_checks_and_keeps_output(tmp_path: Path) -> None:
    fake = FakeRun(lambda cmd: Result(1, f"out:{cmd[2]}", ""))
    out = gate.run_gate(fake, tmp_path)
    assert (out.pytest, out.ruff, out.fmt) == ("out:pytest", "out:ruff", "out:ruff")
    assert "--output-format" in fake.calls[2][0]


def test_checkout_aborts_on_rebase_conflict_and_removes_worktree(tmp_path: Path) -> None:
    fake = FakeRun(
        lambda cmd: Result(1, "", "CONFLICT") if cmd[1] == "rebase" else Result(0, "", "")
    )
    with pytest.raises(gate.RebaseConflict, match="CONFLICT"):
        with gate.checkout(fake, tmp_path, "ref", rebase_onto_main=True):
            pass
    assert [c[0][1] for c in fake.calls] == ["worktree", "rebase", "rebase", "worktree"]
    assert fake.calls[-1][0][2] == "remove"


def test_fetch_returns_pr_ref(tmp_path: Path) -> None:
    fake = FakeRun()
    assert gate.fetch(fake, tmp_path, 12) == "refs/pr-review/12"
    assert fake.calls[1][0][-1] == "pull/12/head:refs/pr-review/12"


def test_agent_ask_is_read_only_and_passes_schema(tmp_path: Path) -> None:
    fake = FakeRun(lambda cmd: Result(0, '{"result": "x"}', ""))
    assert agent.ask(fake, tmp_path, "prompt", "opus") == '{"result": "x"}'
    cmd = fake.calls[0][0]
    assert cmd[:3] == ["claude", "-p", "prompt"] and cmd[-2:] == ["--model", "opus"]
    assert "Edit" in cmd[cmd.index("--disallowedTools") + 1]
    assert json.loads(cmd[cmd.index("--json-schema") + 1])["required"][0] == "approve"
    assert "## Diff" in agent.build_prompt("i", "t", "b", "d", "c")


def test_cli_skip_agent_requires_dry_run() -> None:
    assert cli.main(["--skip-agent"]) == 2


def test_cli_run_pass_counts_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    class Ctx:
        github = GitHub(FakeRun(lambda cmd: Result(0, "[]", "")))
        beads = Beads(FakeRun())

    prs = [PR, PullRequest(8, "t", "b", "bd/om-2", "s", "u")]
    monkeypatch.setattr(Ctx.github, "open_bead_prs", lambda: prs)
    outcomes = iter(["merged", CommandError("boom")])

    def fake_review(ctx: object, pr: PullRequest) -> str:
        value = next(outcomes)
        if isinstance(value, Exception):
            raise value
        return value

    monkeypatch.setattr(cli, "review_pr", fake_review)
    assert cli.run_pass(Ctx(), None) == 1  # type: ignore[arg-type]

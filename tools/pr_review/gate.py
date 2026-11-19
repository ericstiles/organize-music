"""Check out a PR (rebased on origin/main) and run the quality gate there and on main."""

from __future__ import annotations

import sys
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from tools.pr_review.shell import Runner, must

GATE_TIMEOUT = 900.0


class RebaseConflict(RuntimeError):
    """The PR does not rebase cleanly onto origin/main."""


@dataclass(frozen=True)
class GateOutput:
    pytest: str
    ruff: str
    fmt: str


@contextmanager
def checkout(run: Runner, repo: Path, ref: str, rebase_onto_main: bool) -> Iterator[Path]:
    """A throwaway detached worktree at `ref`, optionally rebased onto origin/main."""
    parent = Path(tempfile.mkdtemp(prefix="pr-review-"))
    tree = parent / "tree"
    must(run(["git", "worktree", "add", "--detach", str(tree), ref], cwd=repo), "worktree add")
    try:
        if rebase_onto_main:
            rebased = run(["git", "rebase", "origin/main"], cwd=tree)
            if not rebased.ok:
                run(["git", "rebase", "--abort"], cwd=tree)
                raise RebaseConflict(rebased.err.strip()[:500] or rebased.out.strip()[:500])
        yield tree
    finally:
        run(["git", "worktree", "remove", "--force", str(tree)], cwd=repo)


def fetch(run: Runner, repo: Path, number: int) -> str:
    """Fetch origin/main and the PR head; return the local ref for the PR head."""
    ref = f"refs/pr-review/{number}"
    must(run(["git", "fetch", "-q", "origin", "main"], cwd=repo), "git fetch main")
    must(
        run(["git", "fetch", "-q", "--force", "origin", f"pull/{number}/head:{ref}"], cwd=repo),
        "git fetch PR",
    )
    return ref


def run_gate(run: Runner, tree: Path) -> GateOutput:
    """Run pytest, ruff check and ruff format --check; outputs are kept, exit codes are not."""
    py = sys.executable
    tests = run(
        [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-o", "addopts="],
        cwd=tree,
        timeout=GATE_TIMEOUT,
    )
    ruff = run(
        [py, "-m", "ruff", "check", "--no-cache", "--output-format", "concise", "."],
        cwd=tree,
        timeout=GATE_TIMEOUT,
    )
    fmt = run(
        [py, "-m", "ruff", "format", "--no-cache", "--check", "--output-format", "concise", "."],
        cwd=tree,
        timeout=GATE_TIMEOUT,
    )
    return GateOutput(tests.out + tests.err, ruff.out + ruff.err, fmt.out + fmt.err)

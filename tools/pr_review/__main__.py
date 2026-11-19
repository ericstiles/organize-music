"""CLI: review open Hermes PRs once, or keep watching.

python -m tools.pr_review [--dry-run] [--skip-agent] [--watch SECONDS] [--pr N]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from tools.pr_review.review import Context, review_pr
from tools.pr_review.services import Beads, GitHub
from tools.pr_review.shell import CommandError, run

log = logging.getLogger("pr_review")


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="review_prs", description="Review and merge Hermes PRs.")
    p.add_argument("--dry-run", action="store_true", help="print actions; change nothing")
    p.add_argument("--skip-agent", action="store_true", help="no Claude call (needs --dry-run)")
    p.add_argument("--watch", type=int, default=0, metavar="SECONDS", help="poll interval")
    p.add_argument("--pr", type=int, default=None, help="only this PR number")
    p.add_argument("--model", default=os.environ.get("REVIEWER_MODEL"), help="claude model")
    return p


def run_pass(ctx: Context, only: int | None) -> int:
    """One pass over the open bd/* PRs; returns the number of PRs that hit an error."""
    ctx.beads.pull()
    errors = 0
    prs = [p for p in ctx.github.open_bead_prs() if only is None or p.number == only]
    log.info("%d open bd/* PR(s) to consider", len(prs))
    for pr in prs:
        try:
            log.info("PR #%s: %s", pr.number, review_pr(ctx, pr))
        except (CommandError, ValueError) as exc:
            errors += 1
            log.error("PR #%s: %s", pr.number, exc)
    return errors


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", stream=sys.stdout)
    if args.skip_agent and not args.dry_run:
        log.error("--skip-agent is only allowed with --dry-run")
        return 2
    repo = Path(run(["git", "rev-parse", "--show-toplevel"]).out.strip() or ".")
    ctx = Context(
        run=run,
        repo=repo,
        github=GitHub(run, os.environ.get("REVIEWER_GH_TOKEN") or None),
        beads=Beads(run),
        dry_run=args.dry_run,
        skip_agent=args.skip_agent,
        model=args.model,
    )
    while True:
        try:
            errors = run_pass(ctx, args.pr)
        except CommandError as exc:
            log.error("pass failed: %s", exc)
            errors = 1
        if args.watch <= 0:
            return 1 if errors else 0
        time.sleep(args.watch)


if __name__ == "__main__":
    sys.exit(main())

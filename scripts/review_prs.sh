#!/usr/bin/env bash
# Review open Hermes PRs (branches bd/<id>): gate, ask the reviewer agent, then
# rebase-merge and close the bead, or comment and file tech-debt beads.
#
#   scripts/review_prs.sh --dry-run            # show what it would do, change nothing
#   scripts/review_prs.sh                      # one pass
#   scripts/review_prs.sh --watch 120          # keep polling every 120 s
#   scripts/review_prs.sh --pr 9 --dry-run     # one PR only
#
# Env: REVIEWER_GH_TOKEN  token of a separate GitHub identity; when set the agent
#                         approves / requests changes as that identity, otherwise
#                         it posts comments (GitHub refuses self-approval).
#      REVIEWER_MODEL     claude model for the reviewer (default: claude's default).
# Runs on the host (not in the Hermes sandbox). See docs/AGENTS_WORKFLOW.md.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${REPO_ROOT}/.venv/bin/python"
[ -x "$PY" ] || { echo "missing ${PY}: create the venv first (see CLAUDE.md)" >&2; exit 2; }
for tool in gh bd git claude; do
  command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 2; }
done

cd "$REPO_ROOT"
exec "$PY" -m tools.pr_review "$@"

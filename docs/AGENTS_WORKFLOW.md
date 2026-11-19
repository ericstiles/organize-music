# Agents Workflow

How a beads ticket moves from ready to closed. Hermes implements, Claude
reviews and merges. The rules Hermes follows are in the "Autonomous Beads
workflow" section of [AGENTS.md](../AGENTS.md).

## Ticket lifecycle

```
 hermes-launch (owner)
        │
        ▼
 ┌──────────────────────────────┐
 │ HERMES (sandbox)             │
 │ 1. bd dolt pull              │  sync the ticket queue
 │ 2. bd ready → take 1st item  │──── empty? ──► NO_READY_WORK (stop)
 │ 3. bd update --claim         │  status: in_progress
 │ 4. branch bd/<id> from main  │
 │ 5. write tests → code        │
 │ 6. ruff + pytest             │──── stuck? ──► status: blocked
 │ 7. commit, push, open PR     │                RUN_BLOCKED (stop)
 │    (title and body name id)  │
 │ 8. note PR link on ticket    │  stays in_progress
 │ 9. bd dolt push              │
 └──────────────┬───────────────┘
                │ PR
                ▼
 ┌──────────────────────────────┐
 │ CLAUDE (reviewer)            │
 │ review the PR                │──── bugs? ──► comment on PR /
 │                              │               file new tickets
 │ gh pr merge --rebase         │
 │ bd close <id>                │  status: closed
 └──────────────┬───────────────┘
                │
                ▼
   tickets that depended on it become ready
   → next hermes-launch picks the next one
```

## Which ticket Hermes picks

The first item of:

```bash
bd ready --json --exclude-type epic --sort priority
```

Dependencies decide what is eligible; priority decides the order. To change
what runs next, change priority (`bd update <id> -p 0`) or dependencies
(`bd dep add` / `bd dep remove`).

## Why the ticket stays open until merge

Closing a ticket unblocks its dependents. If Hermes closed it when opening
the PR, the next run would pick a dependent ticket and branch from `main`
before the prerequisite code is there. So the ticket stays `in_progress`
until the PR is merged.

## Reviewer: closing the right ticket

For PR `N`:

```bash
gh pr view N --json headRefName,title,body   # id from branch bd/<id>, title, "Bead: <id>"
bd show <id>                                 # must be in_progress, notes link PR N
gh pr comment N -b "Review: <findings>"      # the review record (see below)
gh pr merge N --rebase
bd close <id> --force --reason "merged PR #N"
bd dolt push
```

- **Comment, not approve:** Hermes opens PRs with the owner's GitHub token, so
  GitHub treats the reviewer's approval as approving your own PR and refuses
  it. The review comment is the record.
- **`--force` on close:** the ticket is assigned to "Hermes Agent" and bd
  refuses to close a ticket assigned to another actor. The reviewer closing
  it on merge is intended, so `--force` is expected here.

If the branch, the PR and the ticket notes disagree, do not merge or close;
ask the owner.

## Reviewer agent (automated)

`scripts/review_prs.sh` runs the steps above unattended on the host. For each
open `bd/*` PR it:

1. checks the bead id agrees across branch, title and `Bead:` line, and that
   the bead is `in_progress` with the PR link (otherwise it comments and skips);
2. rebases the PR onto `origin/main` in a throwaway worktree and runs the
   quality gate there and on `main`, keeping only new failures and findings;
3. asks a headless Claude reviewer (read-only tools, instructions in
   [REVIEWER_AGENT.md](REVIEWER_AGENT.md)) for a JSON verdict;
4. on approval: approves (or comments, without `REVIEWER_GH_TOKEN`),
   rebase-merges with `--match-head-commit`, closes the bead and pushes beads;
5. otherwise: comments with each problem and files one `tech-debt` bead per
   problem (`discovered-from` the ticket), leaving the ticket `in_progress`.

A hidden `<!-- pr-review:<sha> -->` marker in its comment stops it reviewing
the same head commit twice; a new push to the PR gets a fresh review.

```bash
scripts/review_prs.sh --dry-run --skip-agent   # what it would do, no Claude call
scripts/review_prs.sh --watch 120              # review continuously
```

It runs the PR's tests on the host, outside the Hermes sandbox, so only run
it on PRs from this repo's own agents.

## Recovery

| Situation | Command |
|---|---|
| Ticket stuck `in_progress` after a crashed run (no PR) | `bd unclaim <id>` |
| Ticket marked `blocked` and the blocker is fixed | `bd update <id> --status open` |
| PR rejected and closed | `bd update <id> --status open` (or close the ticket as won't-do) |

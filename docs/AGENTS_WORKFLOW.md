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
gh pr merge N --rebase
bd close <id> --reason "merged PR #N"
bd dolt push
```

If the branch, the PR and the ticket notes disagree, do not merge or close;
ask the owner.

## Recovery

| Situation | Command |
|---|---|
| Ticket stuck `in_progress` after a crashed run (no PR) | `bd unclaim <id>` |
| Ticket marked `blocked` and the blocker is fixed | `bd update <id> --status open` |
| PR rejected and closed | `bd update <id> --status open` (or close the ticket as won't-do) |

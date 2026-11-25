# Agent Instructions

**Read `AGENTS_LOCAL.md` before starting any work.** It holds this repository's
own rules and verified facts (environment, quality gate, dependencies,
conventions); this file holds the general workflow. Where they conflict,
`AGENTS_LOCAL.md` wins.

This file is identical in every repository that uses the Hermes harness. The
source of truth is `AGENTS.md` in `hermes-harness`; change it there and copy it
to the other repositories. Put anything repository-specific in `AGENTS_LOCAL.md`.

## Autonomous Beads workflow

Applies to unattended runs started by `hermes-run` (inside the Hermes Docker
sandbox). It is an explicit opt-in to branch, commit, push and open PRs, and
overrides the "Conservative: do not commit or push" default for this workflow
only. Interactive sessions keep the Conservative profile.

### Ticket lifecycle

```
 hermes-run (one Hermes session = one issue)
        │
        ▼
 bd ready --exclude-type epic --sort priority → take the FIRST item
        │                                        (empty → NO_READY_WORK)
        ├─────────────── normal issue T ─────────────────┐
        │                                                ▼
        │                              claim T, branch bd/T from origin/main
        │                              tests first → code → tests + lint
        │                              push, open PR #N:
        │                                title  <type>(T): <summary>
        │                                body   Bead: T
        │                                       Hermes-Session: <id>
        │                              notes on T: "PR: <url>"
        │                              T stays in_progress (blocked? → RUN_BLOCKED)
        │                                                │
        └──── review-fix issue F ────┐                   │
                                     ▼                   │
              claim F, check out the EXISTING branch bd/T│
              read `gh pr view N --comments`             │
              fix every point, push new commits to bd/T  │
              (no new PR, no force-push)                 │
              notes on F: "PR: <url>"; F stays in_progress
                                     │                   │
                                     └─────────┬─────────┘
                                               ▼
 hermes-review (host): new head commit on PR #N → checks + local reviewer model
        │
        ├── approve ──► rebase-merge PR #N
        │               close T and every open review-fix issue for PR #N
        │               → T's dependents become ready
        │
        ├── reject ───► comment on PR #N (each problem, file:line)
        │               create review-fix issue F (label review-fix,
        │                 discovered-from T, links PR #N, branch bd/T,
        │                 Hermes-Session, review checklist)
        │               problems outside the PR's scope → separate tech-debt issues
        │               → next hermes-run picks F
        │
        ├── does not rebase onto main ──► rebase-fix issue F (labels review-fix +
        │                                 rebase-conflict); NOT a rejection strike
        │                                 (after 3 rebase fixes → human, as below)
        │
        └── 2nd reject of the same T ──► T blocked + label human (`bd human list`),
                                         PR labelled needs-human → the owner decides
```

### Rules

- Beads data comes from the Dolt file remote in `.beads/config.yaml`
  (`sync.remote`), which the sandbox mounts at the same path. It is not in git.
  Before anything else:
  - if this clone has no beads database: `bd bootstrap --non-interactive`
  - otherwise: `bd dolt pull`
  Then check `bd stats`. If the remote directory is missing, bootstrap fails,
  or the database has 0 issues, print the reason and `RUN_BLOCKED`, and stop.
  Never fall back to a markdown issue list (e.g. under `docs/`) as the
  queue, and never edit `sync.remote`.
- Print the stop markers `NO_READY_WORK` and `RUN_BLOCKED` alone on their own
  line, exactly as written; the harness classifies the run from them.
- **No human is present.** These runs are unattended: nobody reads your
  messages until the run is over and nobody will answer a question. Never ask
  a question, offer options, or wait for confirmation. A reply without a tool
  call ENDS the session, so only reply without a tool call when you are done:
  the PR URL is printed (step 4), or you printed `RUN_BLOCKED` (step 5), or
  `NO_READY_WORK`. If you are unsure, decide yourself and note the decision in
  the PR body; if you truly cannot continue, that is step 5 (blocked).
- Then `bd prime`. Use `bd` for all tracking; no markdown TODOs.
- **Never replace notes** (`bd update --notes` is blocked: it erases the PR
  link). Only `bd update <id> --append-notes "<line>"`. To tick a checklist
  item, append `- [x] <item>: <evidence>`; never rewrite old lines. Pass
  no `@file` to a bd flag unless `bd <cmd> --help` says it reads files.
  After every bd write, verify with `bd show <id>`; if it did not land, fix it
  or print `RUN_BLOCKED`.
- **Copy bead ids, never retype them.** Take the full id from the claim, the
  `bd ready --json` output or `gh pr view`, and use it unchanged in every
  `bd` command; never shorten it. Short and dotted ids look alike:
  `<prefix>-225` and `<prefix>-b8p.25` are different beads. You may only
  append notes to a bead you claimed in this run (the harness blocks others),
  and the harness itself adds a missing `PR: <url>` line to the PR's beads.
- Do exactly ONE issue per session:
  1. Pick the issue with exactly this command, and take the FIRST item:
     `bd ready --json --exclude-type epic --sort priority`
     (highest priority first; dependencies already filter out anything not
     yet unblocked). Do not pick by title, label or your own judgement, and
     never work an epic: epics are containers closed by their children. If the
     list is empty, run `bd dolt pull` once and repeat the command; if it is
     still empty, print `NO_READY_WORK` and stop. Do not investigate the
     unfiltered list.
  2. `bd update <id> --claim --json`, then `bd dolt push` (so the host sees the
     claim at once), then `bd show <id>`. If the issue has the label
     `review-fix`, follow "Review-fix issues" below instead of steps 3-4.
  3. `git fetch origin`. If the issue's notes have a `WIP:` line (an earlier run
     ran out of time or crashed and saved its work), read it first and, when
     `origin/bd/<id>` exists, continue on it: `git checkout -B bd/<id> origin/bd/<id>`.
     Otherwise branch `bd/<id>` from `origin/main`. Implement test-first, then
     run the quality gate given in `AGENTS_LOCAL.md`.
     At each milestone (tests written, tests pass) run
     `bd update <id> --append-notes "PROGRESS: <milestone>"`: the harness's time
     limit is extended while files are written, commits made or such notes added.
     Scratch files in `/tmp` do not count.
  4. If tests pass: commit, push the branch, open a PR with `gh pr create`
     (base `main`) titled `<type>(<id>): <summary>` (e.g. `fix(<id>): ...`)
     with these lines in the body: `Bead: <id>` and
     `Hermes-Session: <your session id>` (from your system prompt; if it is
     not there, write `Hermes-Session: unknown` and do not search for it).
     Then `bd update <id> --append-notes "PR: <url>"` and verify with
     `bd show <id>` that the `PR:` line is there. Do NOT close the issue:
     it stays `in_progress` so its dependents stay blocked until the PR is
     merged; the reviewer (`hermes-review`) closes it on merge. Print the full
     PR URL on its own line in your final message.
  5. If you hit a blocker: commit WIP to the branch, push it, run
     `bd update <id> --status blocked --append-notes "<why>"`, and print
     `RUN_BLOCKED`. Stop. Don't guess at requirements.
  6. If `hermes-run` resumes you to say the time limit was reached or Hermes
     crashed, do only what that message asks (push WIP, append a `WIP:` note,
     `bd dolt push`, print `RUN_WIP_SAVED`). Do not keep implementing.
- **Review-fix issues** (label `review-fix`, created by `hermes-review` when it
  rejects a PR). The issue names the PR number `N`, the branch `bd/<T>` and the
  original issue `T`.
  1. `git fetch origin`, then check out the EXISTING branch:
     `git checkout -B bd/<T> origin/bd/<T>`. Never branch from main.
  2. Read the review: `gh pr view <N> --comments` and the issue's checklist.
  3. If a point can only be fixed by fixing what another open bead B describes
     (`bd list` / `bd search`; e.g. a coverage gap caused by B's bug), fix B
     here too, and mark it so no later run redoes it: `bd update B --claim`,
     then `bd update B --append-notes "Fixed in PR <url> via review-fix <F>"`
     (that exact line; the reviewer closes B when it merges the PR, so do NOT
     close B). Name B in the commit message and in a PR comment
     (`gh pr comment <N> --body "Also fixes B: <why>"`). If B is already
     claimed by someone else, do not touch it: `bd update <F> --status blocked
     --append-notes "needs B, claimed by <assignee>"`, print `RUN_BLOCKED`
     naming B, and stop.
  4. Fix every point. Tests first for each bug, as in the issue sections below.
     Run the quality gate.
  5. Commit and `git push origin bd/<T>`. Do NOT open a new PR, do NOT
     force-push, do NOT touch the PR title or the `Bead: <T>` line.
  6. `bd update <F> --append-notes "PR: <url>"`, then verify with `bd show <F>`
     and `bd show <T>` that both still have their `PR:` line. Do NOT close F or
     T: the reviewer closes both when it merges the PR. Print the PR URL on its
     own line.
  7. A point you cannot fix in this PR's scope: file it as a new issue (rules
     below) and say so in a PR comment (`gh pr comment <N>`).
  - **Rebase fixes** (labels `review-fix` and `rebase-conflict`, title
    `Rebase PR #N onto main (T)`): the PR only conflicts with main. After step 1,
    run `git rebase origin/main`, resolve each conflict keeping the intent of
    both sides, then run the quality gate. Push with
    `git push --force-with-lease origin bd/<T>`: the ONLY case where a
    force-push is allowed, and only to that branch. Change nothing else. Then
    step 6.
- You ARE allowed and expected to create new beads issues. Do not ask first.
  File one with `bd create "<title>" -t bug|task -p <0-4> --deps discovered-from:<id> -d "<description: sections 1-9>" --design "<sections 10-13>" --acceptance "<section 14>" --silent`
  whenever you:
  - find a bug or gap outside your issue's scope (do not fix it in this PR);
  - resolve a spec conflict by guessing, e.g. an existing test contradicts the
    issue text and you change the test (file it, and say so in the PR body);
  - defer a follow-up, TODO or missing edge case.
  Create at most 3 new issues per run. New issues do not block your current
  PR; finish your issue first. Never close or edit issues you did not claim.
  List the new ids in the PR body and in your final message. Before creating,
  run `bd list --all` and do not file a duplicate.

  **Every issue you create follows this template.** A later agent sees only
  the issue text plus this file, so nothing may be implied. Fill every
  section, or write `N/A: <reason>`; never leave a `<placeholder>`.

  Description (`-d`):
  1. **Goal**: one sentence: the fix or capability delivered.
  2. **Why**: one or two sentences; do not restate a parent epic.
  3. **Current state**: what exists now, with `file:line` references, the
     current behavior, and what was already tried.
  4. **Repro** (bugs only): the exact command(s) or a short script, then
     **Expected:** and **Actual:** (with the error or trace). No repro, no bug.
  5. **In scope**: the behaviors or components to change.
  6. **Expected to modify**: the paths. Touching any other file needs a note
     in the PR body saying why.
  7. **Out of scope / Forbidden**: adjacent work to leave alone, and what
     needs a new bead instead (new dependencies, schema changes, public API
     changes, anything this repo's `AGENTS_LOCAL.md` lists). The stack and
     quality gate live in `AGENTS_LOCAL.md`; do not repeat them here.
  8. **Base branch**: `main`, or the exact branch/PR it must be based on.
  9. **Tests first (TDD, mandatory)**: name each regression test to write
     (file and test function name). The implementer must write these first,
     run them and see each FAIL on the current code for the stated reason,
     then implement until they PASS. The PR body must list the test names and
     paste the failing output from before the fix. Do not weaken or delete an
     existing test to make it pass; if an existing test contradicts the issue,
     say which one and file it per the spec-conflict rule above.

  Design (`--design`):
  10. **Approach**: patterns or helpers to reuse, with paths.
  11. **Invariants**: what must not break (or `N/A: <reason>`).
  12. **Edge cases**: what must be handled (or `N/A: <reason>`).
  13. **Produces for downstream**: the interface or contract other beads rely
      on (or `N/A: <reason>`).

  Acceptance (`--acceptance`):
  14. One `[ ]` line per check a test can assert (exact output, exact exit
      code, exact status), one test per check, plus:
      `[ ] <exact command> passes`,
      `[ ] the quality gate from AGENTS_LOCAL.md passes`,
      `[ ] git diff --stat shows only the Expected-to-modify paths (or the PR
      body explains each other one)`.

  Dependencies are not a section: put them in the graph with
  `--deps blocked-by:<id>` for anything that must land first, and
  `discovered-from:<id>` for issues you found while working. Never only in
  prose.
  Set priority by impact: data loss or security is P1, wrong behavior is P2,
  polish or docs is P3.

  **Standing rules for every issue:**
  - Write it for an agent with no access to your session.
  - Size it to one PR in one run. If it crosses subsystems or would not fit,
    split it into several issues before filing.
  - If, while working an issue, the work needs files outside its Expected to
    modify in another subsystem, or an assumption it rests on fails: file a
    new issue (`discovered-from:<id>`) for the extra work and finish the
    original scope; if the original scope cannot be finished without it,
    follow step 5 (blocked). Do not expand scope.
  - Wrong facts in an issue are not a scope change: follow what you verified
    and name the difference in the PR body (see Working habits).
- Never push to main, never merge, never force-push (sole exception: a rebase
  fix, `--force-with-lease` to its `bd/<T>` branch), never edit CI/secrets
  config, never commit `.envrc.local` or real host names, IPs or paths (use
  the environment variables `AGENTS_LOCAL.md` names).
- Sync beads before finishing (`bd dolt push`).

### Working habits

- Put probes and scratch files outside the repository (in `/tmp`), so the
  commit never needs cleanup.
- When you add a dependency, add it to every file the project installs from
  (manifest, lock file, dev requirements), install it in the local environment,
  and write `New dependency: <name>==<version>` in the PR body. The reviewer's
  quality gate only has what those files list.
- An issue's facts can be wrong. When the code, a library or a test contradicts
  the issue's prose, follow what you verified and name the difference in the
  PR body; do not stop on it.
- If a guard refuses a command, do not retry it or split it to slip past;
  use the form the guard allows. The Hermes sandbox refuses `python3 -c`,
  heredocs, `execute_code`, `rm -rf` on `/tmp` paths and several deletions in
  quick succession: write the script to `/tmp/<name>.py` and run it with the
  project's interpreter, and delete one file per command. There is no `jq`.

### Commits inside the sandbox

The host commit wrappers (`/Users/wilder/repo/pre-commit-scripts/scripts/`) do
not exist in the container. Use plain `git commit` with a conventional-commit
message (`feat:`, `fix:`, `docs:`, `chore:`, `test:` ...).

## Beads basics

This project uses **bd** (beads) for issue tracking. Run `bd prime` for full workflow context.

> **Architecture in one line:** Issues live in a local Dolt database
> (`.beads/dolt/`); cross-machine sync uses `bd dolt push/pull` (a
> git-compatible protocol), stored under `refs/dolt/data` on your git
> remote — separate from `refs/heads/*` where your code lives.
> `.beads/issues.jsonl` is a passive export, not the wire protocol.
>
> See [sync-concepts](https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md)
> for the one-screen overview and anti-patterns (don't treat JSONL as the
> source of truth; don't `bd import` during normal operation; don't
> reach for third-party Dolt hosting before trying the default).

## Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work atomically
bd close <id>         # Complete work
bd dolt push          # Push beads data to remote
```

## Non-Interactive Shell Commands

**ALWAYS use non-interactive flags** with file operations to avoid hanging on confirmation prompts.

Shell commands like `cp`, `mv`, and `rm` may be aliased to include `-i` (interactive) mode on some systems, causing the agent to hang indefinitely waiting for y/n input.

**Use these forms instead:**
```bash
# Force overwrite without prompting
cp -f source dest           # NOT: cp source dest
mv -f source dest           # NOT: mv source dest
rm -f file                  # NOT: rm file

# For recursive operations
rm -rf directory            # NOT: rm -r directory
cp -rf source dest          # NOT: cp -r source dest
```

**Other commands that may prompt:**
- `scp` - use `-o BatchMode=yes` for non-interactive
- `ssh` - use `-o BatchMode=yes` to fail instead of prompting
- `apt-get` - use `-y` flag
- `brew` - use `HOMEBREW_NO_AUTO_UPDATE=1` env var

<!-- BEGIN BEADS INTEGRATION v:1 profile:minimal hash:1105d646 -->
## Beads Issue Tracker

This project uses **bd (beads)** for issue tracking. Run `bd prime` to see full workflow context and commands.

### Quick Reference

```bash
bd ready              # Find available work
bd show <id>          # View issue details
bd update <id> --claim  # Claim work
bd close <id>         # Complete work
```

### Rules

- Use `bd` for ALL task tracking — do NOT use TodoWrite, TaskCreate, or markdown TODO lists
- Run `bd prime` for detailed command reference and session close protocol
- Use `bd remember` for persistent knowledge — do NOT use MEMORY.md files

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.

## Agent Context Profiles

The managed Beads block is task-tracking guidance, not permission to override repository, user, or orchestrator instructions.

- **Conservative (default)**: Use `bd` for task tracking. Do not run git commits, git pushes, or Dolt remote sync unless explicitly asked. At handoff, report changed files, validation, and suggested next commands.
- **Minimal**: Keep tool instruction files as pointers to `bd prime`; use the same conservative git policy unless active instructions say otherwise.
- **Team-maintainer**: Only when the repository explicitly opts in, agents may close beads, run quality gates, commit, and push as part of session close. A current "do not commit" or "do not push" instruction still wins.

## Session Completion

This protocol applies when ending a Beads implementation workflow. It is subordinate to explicit user, repository, and orchestrator instructions.

1. **File issues for remaining work** - Create beads for anything that needs follow-up
2. **Run quality gates** (if code changed) - Tests, linters, builds
3. **Update issue status** - Close finished work, update in-progress items
4. **Handle git/sync by active profile**:
   ```bash
   # Conservative/minimal/default: report status and proposed commands; wait for approval.
   git status

   # Team-maintainer opt-in only, unless current instructions forbid it:
   git pull --rebase
   git push
   git status
   ```
5. **Hand off** - Summarize changes, validation, issue status, and any blocked sync/commit/push step

**Critical rules:**
- Explicit user or orchestrator instructions override this Beads block.
- Do not commit or push without clear authority from the active profile or the current user request.
- If a required sync or push is blocked, stop and report the exact command and error.
<!-- END BEADS INTEGRATION -->

<!-- BEGIN BEADS CODEX SETUP: generated by bd setup codex -->
## Beads Issue Tracker

Use Beads (`bd`) for durable task tracking in repositories that include it. Use the `beads` skill at `.agents/skills/beads/SKILL.md` (project install) or `~/.agents/skills/beads/SKILL.md` (global install) for Beads workflow guidance, then use the `bd` CLI for issue operations.

### Quick Reference

```bash
bd ready                # Find available work
bd show <id>            # View issue details
bd update <id> --claim  # Claim work
bd close <id>           # Complete work
bd prime                # Refresh Beads context
```

### Rules

- Use `bd` for all task tracking; do not create markdown TODO lists.
- Run `bd prime` when Beads context is missing or stale. Codex 0.129.0+ can load Beads context automatically through native hooks; use `/hooks` to inspect or toggle them.
- Keep persistent project memory in Beads via `bd remember`; do not create ad hoc memory files.

**Architecture in one line:** issues live in a local Dolt DB; sync uses `refs/dolt/data` on your git remote; `.beads/issues.jsonl` is a passive export. See https://github.com/gastownhall/beads/blob/main/docs/core-concepts/sync-concepts.md for details and anti-patterns.
<!-- END BEADS CODEX SETUP -->

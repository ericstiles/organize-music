# Agent Instructions

## Autonomous Beads workflow

Applies to unattended runs started by `hermes-run` (inside the Hermes Docker
sandbox). It is an explicit opt-in to branch, commit, push and open PRs, and
overrides the "Conservative: do not commit or push" default for this workflow
only. Interactive sessions keep the Conservative profile.

- Beads data comes from the Dolt file remote in `.beads/config.yaml`
  (`sync.remote`), which the sandbox mounts at the same path. It is not in git.
  Before anything else:
  - if this clone has no beads database: `bd bootstrap --non-interactive`
  - otherwise: `bd dolt pull`
  Then check `bd stats`. If the remote directory is missing, bootstrap fails,
  or the database has 0 issues, print the reason and `RUN_BLOCKED`, and stop.
  Never fall back to `docs/WEB_UI_ISSUES.md` or any markdown list as the
  queue, and never edit `sync.remote`.
- Print the stop markers `NO_READY_WORK` and `RUN_BLOCKED` alone on their own
  line, exactly as written; the harness classifies the run from them.
- Then `bd prime`. Use `bd` for all tracking; no markdown TODOs.
- Do exactly ONE issue per session:
  1. `bd ready --json`. If empty, print `NO_READY_WORK` and stop.
  2. `bd update <id> --claim --json`, then `bd show <id>`.
  3. Branch `bd/<id>` from latest `origin/main`. Implement test-first, then run
     the quality gate: `ruff check . && ruff format --check . && pytest`.
  4. If tests pass: commit, push the branch, open a PR with `gh pr create`
     (base `main`), then `bd close <id> --reason "<summary + PR link>" --json`.
  5. If you hit a blocker: commit WIP to the branch, push it, run
     `bd update <id> --status blocked --append-notes "<why>"`, and print
     `RUN_BLOCKED`. Stop. Don't guess at requirements.
- You ARE allowed and expected to create new beads issues. Do not ask first.
  File one with `bd create "<title>" -t bug|task -p <0-4> --deps discovered-from:<id> -d "<self-contained description>" --acceptance "<checks a test can assert>" --silent`
  whenever you:
  - find a bug or gap outside your issue's scope (do not fix it in this PR);
  - resolve a spec conflict by guessing, e.g. an existing test contradicts the
    issue text and you change the test (file it, and say so in the PR body);
  - defer a follow-up, TODO or missing edge case.
  Create at most 3 new issues per run. New issues do not block your current
  PR; finish your issue first. Never close or edit issues you did not claim.
  List the new ids in the PR body and in your final message. Before creating,
  run `bd list --all` and do not file a duplicate.

  **Every issue you create must contain these sections** (a later agent sees
  only the issue text plus this file, so nothing may be implied):
  1. **Problem**: what is wrong or missing, and where (file and function).
  2. **Repro** (bugs): the exact command(s) or a short script, with the
     observed output and the expected output. No repro, no issue.
  3. **Fix scope**: what to change, and a "Do NOT change" list. It must fit one
     PR in one run; if it does not, split it into several issues.
  4. **Base branch**: `main`, or the exact branch/PR it must be based on.
  5. **Tests first (TDD, mandatory)**: name each regression test to write
     (file and test function name). The implementer must write these first,
     run them and see each FAIL on the current code for the stated reason,
     then implement until they PASS. The PR body must list the test names and
     paste the failing output from before the fix. Do not weaken or delete an
     existing test to make it pass; if an existing test contradicts the issue,
     say which one and file it per the spec-conflict rule above.
  6. **Acceptance** (`--acceptance`): checks a test can assert (exact status
     codes, exact output, exact exit codes), one test per check.
  7. **Constraints**: Python >= 3.12, stdlib plus existing dependencies only,
     files not to touch, the quality gate above, existing tests must keep
     passing, and conventional commit messages.
  8. **Dependencies**: `--deps blocked-by:<id>` for anything that must land
     first; only `discovered-from:<id>` for issues you found while working.
  Set priority by impact: data loss or security is P1, wrong behavior is P2,
  polish or docs is P3.
- Never push to main, never merge, never force-push, never edit CI/secrets
  config, never commit `.envrc.local` or real host names, IPs or paths (use
  the `$PI_HOST` / `$MUSIC_LIB` environment variables).
- Sync beads before finishing (`bd dolt push`).

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

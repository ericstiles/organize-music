# CLAUDE.md - AI Development Orientation Guide

## Project Overview
`organize_music`: CLI tools and automation scripts for organizing a music library (metadata extraction, audio file de-duplication, and directory restructuring). Companion tools for music stored on the Raspberry Pi 5 SSD.

## Tech Stack & Tooling
- **Language**: Python >= 3.12 (standard library + targeted audio libraries like `mutagen`)
- **Virtual Environment**: `.venv` in repository root
- **Test Runner**: `pytest` (strict markers, fast deterministic unit tests)
- **Linter & Formatter**: `ruff` (line-length: 100, pycodestyle, pyflakes, isort, bugbear)
- **Git Conventions**: Conventional Commits only (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`)

## Essential Commands
```bash
# Setup & Environment
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

# Verification & Testing
pytest                        # Run all unit tests
pytest -v -k "test_smoke"     # Run focused test
ruff check .                  # Lint codebase
ruff format --check .         # Check formatting
ruff format .                 # Auto-format files

# Full Quality Gate (Run before committing)
ruff check . && ruff format --check . && pytest
```

## Directory Architecture
```
organize_music/
├── .venv/                  # Local isolated Python environment (gitignored)
├── docs/                   # Specifications, tasks, and documentation (UPPERCASE_WITH_UNDERSCORES.md)
│   ├── SPECS.md            # Feature requirements & behavioral contracts
│   └── TASKS.md            # Granular, checkable development tasks
├── scripts/                # Standalone shell scripts & executable entry points
├── src/organize_music/     # Core modular Python package
│   ├── config.py           # Paths, constants, and environment defaults
│   ├── dedup.py            # Audio duplicate detection & comparison logic
│   ├── metadata.py         # Tag reading, normalization, and validation
│   └── organizer.py        # Safe filesystem operations & directory reorganizer
├── tests/                  # Deterministic unit and integration tests
│   ├── test_dedup.py
│   ├── test_metadata.py
│   ├── test_organizer.py
│   └── test_smoke.py
├── pyproject.toml          # Project config, pytest settings, ruff rules
└── README.md               # High-level repo summary
```

## Coding Guardrails & Standards
1. **Modularity & File Size**: Max 200 lines per file. Single responsibility per module.
2. **Type Annotations**: Mandatory explicit type hints on all function signatures and return types.
3. **Safety First**: Any filesystem mutation (move, delete, rename) **must** support a `--dry-run` mode and fail-fast validation before execution.
4. **Pure Logic Separation**: Separate pure business logic (tag parsing, duplicate matching) from side effects (disk I/O, network).
5. **Naming Conventions**:
   - Python files: `snake_case.py`
   - Shell scripts: `scripts/snake_case.sh` (or `kebab-case.sh`)
   - Markdown docs: `UPPERCASE_WITH_UNDERSCORES.md`
6. **No Phantom Code**: No placeholder functions, dead imports, or untested branches.

## Unattended runs (Hermes)
Unattended `hermes-run` sessions follow the **"Autonomous Beads workflow"** section of
`AGENTS.md`, which opts them in to branch, commit, push and open PRs (never push to `main`,
never merge). Interactive sessions keep the Conservative profile below.

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

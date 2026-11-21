# Project-Specific Agent Rules (organize_music)

`AGENTS.md` holds the general workflow, which applies to any agent. This file
holds the rules and facts that only apply to this repository. Read it before
starting work. If the two conflict, this file wins for this repository.

## Environment

- Stack: Python >= 3.12, standard library plus the dependencies already in
  `pyproject.toml`; adding one follows "Dependencies" below.
- Never commit real host names, IPs or library paths: use `$PI_HOST` and
  `$MUSIC_LIB` (set in the untracked `.envrc.local`).
- `docs/WEB_UI_ISSUES.md` is the planning catalogue, not the work queue; the
  queue is beads only. The full ticket lifecycle is in `docs/AGENTS_WORKFLOW.md`.
- Use the repo's virtualenv for everything: `.venv/bin/python`,
  `.venv/bin/pytest`, `.venv/bin/ruff`. The system `python3` does not have the
  project's dependencies.
- Quality gate (must pass before every commit):
  `.venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/pytest -q`
- Put probe and scratch scripts in `/tmp`, never in `scripts/`. `scripts/` holds
  shipped entry points, and a probe left there fails `ruff` and must be deleted
  before the commit.

## Dependencies

- `pyproject.toml` is the source of truth. Pin new runtime dependencies the way
  the existing ones are pinned. If the dependency is needed to run the tests,
  also add it to `requirements-dev.txt`.
- Install it right away: `.venv/bin/pip install -e '.[dev]'`
  (and `-r requirements-dev.txt` if you changed that file).
- Write `New dependency: <name>==<version>` in the PR body. The reviewer's
  quality gate runs in the host's `.venv`, which only gets a new package when
  someone installs it there.

## Database and migrations (`src/organize_music/db/`)

- Migrations are forward-only. Never edit a migration that has shipped
  (e.g. `0001_initial.sql`); add a new numbered file instead.
- No `DROP` anywhere under `src/organize_music/db/` and no `*.rollback.sql`
  files (PR #32 adds a test that enforces both).
- Keep the public API of `db/migrations.py` stable:
  `SchemaTooNew`, `available(migrations_dir=None)`,
  `migrate(conn, db_path, backups_dir, now, migrations_dir=None) -> int`.
- yoyo-migrations 9.0.0 facts, verified in a run (2026-11-21):
  - the table of applied migrations is `_yoyo_migration` (singular), with
    columns `migration_hash`, `migration_id`, `applied_at_utc`
  - `migration_hash` hashes the migration id, not the file content
  - `get_backend()` needs an absolute `sqlite:///` path; `read_migrations()`
    needs `str` paths
  - apply with `backend.apply_one(m)` inside `with backend.lock():`, so a
    failing migration raises and rolls back

## Guardrails from CLAUDE.md that reviewers check

- Max 200 lines per Python file; split into a helper module instead.
- Type hints on every function signature.
- Any filesystem mutation (move, delete, rename) supports `--dry-run`.

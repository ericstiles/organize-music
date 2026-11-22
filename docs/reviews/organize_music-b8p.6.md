# Review: Migration runner (b8p.5) and its yoyo move (b8p.37)

Paired review of `organize_music-b8p.5` (forward-only migration runner with an
online backup and the `0001_initial` schema, PR #26, merge commit `3c27b0e`)
**together with** `organize_music-b8p.37` (the runner moved onto
yoyo-migrations 9.0.0 plus a checksum guard against edited migration files,
closed as "all children merged" on PRs #35, #38, #39, #41, #42; the children are
`b8p.37.1.1`/`b8p.37.1.2`/`b8p.37.2`/`b8p.37.3`/`b8p.37.4`/`b8p.37.5`). The
review target is the code as it is on `main` after b8p.37 landed, and it also
re-checks the acceptance criteria of b8p.5 (all listed tests pass; no `DROP` in
`src/organize_music/db/`) and of each b8p.37 child. Catalogue id P1-4-R.

Reviewer: Hermes run `20261122_145353_a125d5` (**model qwen3.8-27**). The issue
is unlabelled for a specific model (no `model:opus-5.5` on it, unlike the paired
`-R` reviews in b8p.37's children), so there is no model mismatch to flag here.

## Verdict

**Approve.** No safety findings. Nothing blocks the next phase (P1-13/P1-14, the
files and operation-log repositories that this review's dependents gate), and no
new issue is filed. The module that performs the disk work of *migration* —
`src/organize_music/db/migrations.py` (196 lines) plus its helper
`src/organize_music/db/migration_checksums.py` (118 lines) and the `WriterLock`
in `connection.py` (68 lines) — is correct and safe: the no-unsafe-calls guard is
effective (proven by a plant), nothing in the migration path can replace or
delete a library file, every refuse path is byte-identical, every crash point is
covered by a purpose-built test, and the quality gate is green.

The review re-read PLAN §5 (the schema) and §6.1/§6.4/§11 (the migration and
crash-matrix rules), compared them to the merged code line by line, hand-searched
the diff and the whole `src/organize_music` tree for every forbidden call, ran a
throwaway plant to confirm the no-unsafe-calls guard still fails on a real
violation, and ran the project's quality gate on this branch.

## What the module does (and why the checklist items scope the way they do)

The migration runner's only *disk* side effect is `conn.backup()` copying
`library.db` into `backups_dir/` (`migrations.py:90-99`). It creates tables,
views, indexes and triggers *inside* the database file; it never touches the
music files on disk. The crash-matrix invariant I3/I5 ("at most one in-flight
operation per file" / "no operation stays non-terminal at rest") is a property of
the *operations* layer (the journaled move / retag of P1-13/P1-14), which is not
built yet — exactly the scoping the b8p.12 (crash-test harness) and b8p.21
reviews used for the support/primitive modules this layer sits on. So two of the
seven checklist items are correctly N/A for this module, and the crash-resilience
guarantees that *are* this module's job are discharged by purpose-built
crash-simulation tests rather than by the FaultyFs matrix (which has nothing to
drive yet).

## Checklist (every item ticked, with evidence)

- **Plan §5 read; code compared line by line.** PLAN §5's schema is shipped
  **verbatim** in `src/organize_music/db/migrations/0001_initial.sql` (118
  lines): `settings`, `files` (with the `CHECK ((status='gone')=(path IS NULL))`,
  `CHECK ((path IS NULL)=(path_key IS NULL))`, and
  `CHECK ((audio_hash IS NULL)=(hash_kind IS NULL))` constraints), the partial
  `files_path_key` unique index, the `songs` view, and the FTS5
  `files_fts` external-content virtual table with the three `AFTER INSERT/UPDATE/
  DELETE` sync triggers (`0001_initial.sql:42-64`). Plus `batches`, `operations`
  (with the `operations_one_active_per_file` partial index,
  `0001_initial.sql:96-97`) and `events`/`jobs`. `test_fresh_db_reaches_version_1_
  with_all_schema_objects` (`tests/db/test_migrations.py:103-127`) asserts every
  one of these objects exists after a fresh `migrate`. No drift from §5.

- **Crash-matrix test (FaultyFs before/after each fs call) + recovery +
  assert_consistent, where the module performs disk changes.** N/A as an
  *operations-layer* property, for the reason in the section above: the runner's
  only disk write is `conn.backup()`, and the per-file crash matrix is the
  responsibility of P1-13/P1-14 (the move/retag operations), not the migration
  runner. What this module *is* responsible for — crash resilience across its own
  two independent writes (yoyo's `_yoyo_migration` record vs. the runner's
  `migration_checksums` row vs. the `user_version` bump) — is covered by
  purpose-built tests that simulate exactly those crashes and assert recovery:
  `test_lagging_user_version_is_repaired_not_reapplied`
  (`tests/db/test_migrations.py:558-592`, a crash between the yoyo record and the
  `user_version` bump → repair, not re-apply), `test_missing_checksum_row_is_
  backfilled_with_warning` (`:670-694`, a crash between yoyo's record and the
  checksum row → backfill + warning), and `test_failing_migration_rolls_back_
  and_is_not_recorded` (`:332-372`, a half-applied migration → no yoyo row, no
  checksum row, `user_version` unchanged). Same N/A scoping as the b8p.12/b8p.21
  reviews; no defect.

- **No code path can replace or delete a library file.** Verified three ways.
  1. *Hand search of the whole `src/organize_music` tree.* The only raw
     forbidden calls are `fsops/primitives.py:173` `candidate.unlink()` (the
     guarded `discard_temp` unlink, reviewed in b8p.10) and `fsops/protocol.py:104`
     `os.replace(tmp, path)` in `write_text_atomic` (the one sanctioned
     *report*-path write, reviewed in b8p.12); both live in `fsops/`, which the
     guard excludes. `markdown.py:10` is `str.replace("|", ...)` — a string op,
     the single reviewed `_ALLOWED` exception. **The migration path
     (`db/migrations.py`, `db/migration_checksums.py`) contains zero raw
     filesystem replace/delete/rename/remove/rmtree/move calls** — its only I/O is
     `conn.backup()`, `conn.execute(...)`, `hashlib.sha256(...).read_bytes()`
     (reads of the *shipped migration SQL files*, not library files) and
     `backups_dir.mkdir(...)`.
  2. *The guard test is effective, not merely present.* Planting
     `os.remove("x")` in a new `src/organize_music/_probe_tmp.py` made
     `tests/test_no_unsafe_calls.py::test_no_unsafe_filesystem_calls_outside_fsops`
     fail with `_probe_tmp.py:3: os.remove()  ->  os.remove("x")`; after deleting
     the probe it passed (`3 passed`). The guard is real.
  3. *The guard's own scope.* `tests/test_no_unsafe_calls.py:6` greps every
     `*.py` under `src/organize_music` except `fsops/`; the migration modules are
     in scope and clean. No code path in the migration runner can replace or
     delete a library file.

- **Preconditions (path, size, mtime_ns, row_version) checked before the first
  disk change.** N/A as a migration-runner responsibility: those preconditions
  belong to the operations layer (P1-13/P1-14), which reads `expect_path` /
  `expect_size` / `expect_mtime_ns` / `expect_row_version` from the `operations`
  table (`0001_initial.sql:88-89`) — the schema this issue ships, and which
  b8p.5's `test_status_gone_with_a_path_fails_the_check`
  (`tests/db/test_migrations.py:200-208`) and
  `test_casefolded_path_keys_collide_in_the_unique_index` (`:211-221`) already
  exercise against the `files` constraints. The migration runner itself holds and
  checks no such precondition; its only "preconditions" are the refuse checks in
  the next item, which correctly run before any write.

- **Errors are explicit and use the documented codes; no bare except, no
  `except: pass`, nothing swallowed.** The migration path uses two explicit,
  documented exception types: `SchemaTooNew` (`migrations.py:42`, raised with a
  message naming the offending version or unknown ids — `:141-144`, `:151-154`)
  and `MigrationChanged` (`migration_checksums.py:30-35`, carrying the migration
  id, raised on a checksum mismatch — `:97-98`). A half-applied migration
  propagates yoyo's `sqlite3.OperationalError` unchanged (proven by
  `test_failing_migration_rolls_back_and_is_not_recorded`, `:346`). A hand grep
  of `src/organize_music` for `except\s*:` and `except[^:]*:\s*pass` returns
  **nothing**. The only `except` clauses in the db module are the explicit
  `finally` cleanup in `connection.py:56-60` (WriterLock's
  `except BaseException` that closes the fd and *re-raises*) and
  `migrations.py:95-99` / `:194-195` (the `finally` that closes the yoyo
  backend's connection), neither of which swallows. Nothing is swallowed.

- **Tests written first, covering the failure cases in b8p.5.** b8p.5's list
  (fresh DB → all §5 objects; migrate twice is a no-op; `user_version` 99 →
  `SchemaTooNew` and DB untouched; fake 0002 → backup appears before it applies;
  `status='gone'`+path fails the CHECK; casefolded `path_key` collides; FTS finds
  a row by artist and not after update) are all present and green:
  `test_fresh_db_reaches_version_1_with_all_schema_objects` (`:103`),
  `test_migrate_twice_is_a_noop` (`:130`),
  `test_user_version_newer_than_code_refuses_to_open` (`:144`) /
  `..._refuses_and_touches_nothing` (`:504`),
  `test_backup_is_taken_before_a_pending_migration_applies` (`:158`),
  `test_status_gone_with_a_path_fails_the_check` (`:200`),
  `test_casefolded_path_keys_collide_in_the_unique_index` (`:211`), and
  `test_fts_syncs_with_insert_and_update` (`:224`). b8p.37's failure cases are
  likewise present: unknown applied id → `SchemaTooNew` and byte-identical DB
  (`test_applied_id_unknown_to_code_refuses_and_touches_nothing`, `:475`),
  edited applied migration → `MigrationChanged` and nothing applied
  (`test_edited_applied_migration_raises_migration_changed`, `:649`), missing
  checksum row → backfill + warning (`:670`), failing migration → rolled back and
  not recorded (`:332`), old-runner DB adopted without re-running 0001
  (`:392`/`:418`), lagging `user_version` repaired not re-applied (`:558`), and
  the yoyo backend connection is closed on every return path
  (`test_yoyo_backend_connection_is_closed`, `:595`). TDD is recorded in the PRs
  (the b8p.37.4 WIP note: "TDD red-phase complete … ImportError: MigrationChanged
  = RED").

- **Files <= 200 lines, typed signatures, no dead code.** `migrations.py` is
  196 lines, `migration_checksums.py` 118, `connection.py` 68 — all under 200, and
  `tests/test_file_length.py` (which scans `src/organize_music` only) is green.
  Every public signature is typed: `available(migrations_dir: Path | None = None)
  -> list[tuple[int, str]]` (`migrations.py:46`),
  `migrate(conn: sqlite3.Connection, db_path: Path, backups_dir: Path, now: str,
  migrations_dir: Path | None = None) -> int` (`:116-122`),
  `MigrationChanged.__init__(self, migration_id: str) -> None`
  (`migration_checksums.py:33`),
  `ensure_checksum_table(conn: sqlite3.Connection) -> None` (`:38`),
  `record_checksum(conn: sqlite3.Connection, migration_id: str, path: str,
  now: str) -> None` (`:52`),
  `verify_checksums(conn: sqlite3.Connection, applied_ids: set[str],
  id_to_path: dict[str, str], now: str) -> None` (`:67-72`). No dead code:
  `ruff check .` (incl. F401/F811/F841) is clean and every `__all__` entry is
  exercised by a test. `tests/db/test_migrations.py` is 694 lines, but the
  200-line limit scans `src/` only (same scoping as b8p.21), so it is out of
  scope by design.

## b8p.37 acceptance criteria, re-checked

- **Public API of `db/migrations.py` unchanged from b8p.5** (`SchemaTooNew`,
  `available(migrations_dir=None)`, `migrate(conn, db_path, backups_dir, now,
  migrations_dir=None) -> int`): confirmed — `migrations.py:33,46,116-122`; the
  children each restated "Do NOT adopt the label / backup_dir signature" and the
  signature is intact. (`MigrationChanged` is *added* to `__all__` as the
  b8p.37.4 guard, not a signature change.)
- **Forward-only / no `DROP` / no `*.rollback.sql`**: `grep -rn 'DROP'
  src/organize_music/db/` returns no output (and `test_package_has_no_rollback_
  files_and_no_drop_statements`, `tests/db/test_migrations.py:458-472`, asserts
  both and is green); `find src/organize_music -name '*.rollback.sql'` is empty;
  nothing calls yoyo rollback.
- **Checksums in `migration_checksums`** (`b8p.37.3`): table shape
  `(migration_id TEXT PRIMARY KEY, sha256 TEXT NOT NULL, applied_at TEXT NOT
  NULL)`, created by the runner via `CREATE TABLE IF NOT EXISTS`
  (`migration_checksums.py:44-48`), one row recorded after each apply
  (`record_checksum`, `:52-64`; `migrations.py:187`), and a failing migration gets
  no row — all confirmed by tests.
- **`MigrationChanged` guard + backfill** (`b8p.37.4`): verified in
  `verify_checksums` (`migration_checksums.py:67-110`) — a mismatch raises and
  touches nothing (`:97-98`), a missing row is backfilled with the current file's
  hash and a `logging` warning (`:99-105`), confirmed by `:649`/`:670`.
- **Pending picked from yoyo state, not `user_version`; backend connection
  closed** (`b8p.37.5`): `migrations.py:185` drives `backend.to_apply(...)`,
  `:191-192` sets `user_version` to the highest applied number, and
  `:194-195`/`test_yoyo_backend_connection_is_closed` close the backend connection
  on every return path.
- **yoyo-migrations pinned**: `yoyo-migrations==9.0.0` in `pyproject.toml:20`
  **and** `requirements-dev.txt:6` (the `iyg` follow-up added it to the dev list).
- **Old-runner adoption** (`b8p.37.1.2`): `mark_migrations(to_adopt)`
  (`migrations.py:175-176`) records already-shipped ids without re-running them,
  so 0001 runs once on a legacy DB (`test_old_runner_db_is_adopted_...`, `:392`).
- **b8p.5 acceptance** ("all listed tests pass; no `DROP`"): both green.

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.6` (from `origin/main` `594eb16`), run under the project
venv (Python 3.13.5, which satisfies `requires-python >=3.12`; the sandbox's
system `python` is 3.11 and lacks the project deps, so the venv is used, as in
the b8p.12/b8p.21 reviews — the gate is mechanical, not a runtime pin):

```
ruff check .          -> All checks passed!
ruff format --check . -> 82 files already formatted
pytest -q            -> 306 passed, 1 skipped, 2 warnings
```

The 1 skip is `test_rename_noreplace_case_only_raises_on_case_insensitive`,
skipped because the sandbox's filesystem is case-sensitive (it runs on the Pi's
exFAT and on APFS). The 2 warnings are a yoyo-migrations `DeprecationWarning`
(default datetime adapter) from `test_migrations.py`, unrelated to this change.
`tests/test_no_unsafe_calls.py` (3 passed) and `tests/test_file_length.py`
(1 passed) are green.

## Findings

None blocking. No safety findings, nothing blocks the next phase, no new issue
filed. Three observations, none a code or safety defect:

- *Observation (crash-matrix scoping, not a defect).* As in b8p.12/b8p.21, the
  per-file FaultyFs crash matrix does not yet apply to this module: it is the
  *migration* layer, and the in-flight-per-file invariant lives in the
  operations layer (P1-13/P1-14, not built). The module's own crash resilience
  (the three-way split between yoyo's record, the checksum row, and
  `user_version`) is instead proven by the purpose-built crash-simulation tests
  listed above, which is the correct and complete treatment.
- *Observation (table-name wording, not a defect).* The applied-migration table
  is `_yoyo_migration` (singular, `_YOYO_TABLE` at `migrations.py:39`, with the
  comment "plural in the docs, singular on disk"); the b8p.37.1/.2/.3 issue text
  and the parent WIP note wrote it `_yoyo_migrations` (plural), and the parent's
  own notes carried the same slip. The shipped code, its tests
  (`SELECT ... FROM _yoyo_migration`, `tests/db/test_migrations.py:275,359,...`),
  and the AGENTS_LOCAL yoyo facts all agree on the singular; the difference is a
  wording nit in the issue prose, not a code issue.
- *Observation (lock discipline, not a defect).* `migrate` opens its own yoyo
  backend connection to the same file (`migrations.py:170`, closed in `finally`
  at `:194-195`). b8p.37's item 1 ("run only inside `WriterLock`") is a
  *call-site* invariant: `WriterLock` (`connection.py:38-67`) is the public
  entry and no production caller of `migrate` exists yet, so the "run inside the
  lock" contract is enforced by the (future) CLI/server callers rather than by
  `migrate` itself. This is consistent with the runner being a library primitive;
  flagged for the P1-13/P1-14 reviews to assert that their callers hold
  `WriterLock` around `migrate`. Not a defect and not a blocker.

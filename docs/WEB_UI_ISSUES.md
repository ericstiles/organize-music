# Web UI Issue Catalogue

Companion to [WEB_UI_PLAN.md](WEB_UI_PLAN.md). The session that creates the beads issues expands
each row into a full issue: why, scope and out-of-scope, the quoted plan decision, tests to write
first, done-commands, and the model on the first line and as a label. **That session should run on
Claude Fable 5.2 or Opus 5.5**: issue text is the implementer's whole context.

Conventions for every issue:
- Paths are under `src/organize_music/`; tests are under `tests/`; every file stays ≤ 200 lines.
- **Done-command** for every issue unless stated otherwise:
  `ruff check . && ruff format --check . && pytest -q` → exit 0, no new skips.
- **Review pairing:** every row marked **R** gets a paired review issue `<id>-R`. It depends on the
  implementation issue and blocks everything that depends on that issue. The review checklist:
  every state transition has a crash-matrix test; no code path can replace or delete a library
  file (§6.1 grep test passes); preconditions are checked before the first disk change; errors use
  `errors.py` codes; nothing is swallowed.
- Labels: `phase:N`, `model:<model>`, plus `mutation-path` where **R**. One epic per phase.
- Every phase ends with `PN-END`: "End-of-phase review", model `opus-5.5`, depending on every
  issue in the phase. The first issue of the next phase depends on it.

Models: `qwen` = `model:qwen3.8-27`, `opus` = `model:opus-5.5`, `sonnet` = `model:sonnet-5.5`,
`fable` = `model:fable-5.2`, `owner+opus` = owner present with Opus driving.

## Phase 0: Stabilise (epic)

| Id | Title | Files | Key contents | Model | Review | Depends |
|----|-------|-------|--------------|-------|--------|---------|
| P0-1 | Restore `render_metadata_report` in reports.py | `reports.py`, `tests/test_reports.py` | Restore the `def` line from `main`; remove the unreachable code after `render_name_preview_report`'s `return`; both renderers tested | qwen | sonnet | – |
| P0-2 | Restore `run_dupes` in cli.py | `cli.py` | Restore verbatim from `git show main:src/organize_music/cli.py`; `tests/test_cli.py` dupes tests pass | qwen | sonnet | P0-1 |
| P0-3 | Remove the `rename` subcommand and `rename.py` | `cli.py`, `rename.py`, `tests/test_rename.py`, `tests/test_cli_rename.py` | Delete all four (code, not library files); `organize-music rename` → argparse error; reason: plan C4 | qwen | sonnet | P0-2 |
| P0-4 | naming.py: `render_name` sanitises each segment | `naming.py`, `tests/test_naming*.py` | `render_name(template: str, track: TrackMetadata) -> str` splits on `/`, sanitises each rendered segment, preserves `.ext`; fix imports; existing sanitize tests unchanged. Vocabulary is **not** changed here (P4-1) | qwen | sonnet | P0-3 |
| P0-5 | Lint and format the branch clean | tests touched by `3c558bd`..`2a9ee13` | `ruff check --fix`, `ruff format`, wrap E501 lines by hand; no behaviour change | qwen | sonnet | P0-4 |
| P0-6 | Split cli.py under 200 lines | `cli.py`, new `cli_commands.py` | Move `run_meta`, `run_hash`, `run_dupes`, `run_tags` into `cli_commands.py`; `cli.py` keeps the parser and `main`; add `tests/test_file_length.py` asserting every `src/**/*.py` ≤ 200 lines | qwen | sonnet | P0-5 |
| P0-7 | Deploy must not delete state | `scripts/deploy_to_pi.sh`, `config.py`, `config.example.yaml`, `tests/test_config.py` | Add `--exclude 'state/'`; default `index` → `~/.local/share/organize_music/index.db`; a test asserts the default index is not under `~/organize_music` | qwen | **opus** | – |
| P0-8 | Docs point at the new plan | `docs/TASKS.md`, `docs/PLAN.md` | TASKS.md body → pointer to beads and WEB_UI_PLAN; PLAN.md decisions 4 and 5 and "Collisions" marked superseded with links | qwen | sonnet | P0-6 |

Tracker hygiene (§13 of the plan) is done by the issue-writing session itself, not as an issue.

## Phase 1: Tracer bullet (epic)

| Id | Title | Files | Key contents | Model | R | Depends |
|----|-------|-------|--------------|-------|---|---------|
| P1-1 | Add web and tag-write dependencies | `pyproject.toml`, `requirements-dev.txt` | fastapi, uvicorn, jinja2, python-multipart, itsdangerous, mediafile; dev: httpx. `python -c "import fastapi, mediafile"` | qwen | | P0-END |
| P1-2 | Config: library_mount, work_dir, state_dir, bind, mutations flag | `config.py`, tests | New keys `library_mount`, `work_dir`, `purge_dir`, `state_dir`, `bind_host`, `bind_port`, `mutations_enabled` (default false); `work_dir` and `purge_dir` outside the library; same-device check is P1-6 | qwen | | P1-1 |
| P1-3 | DB connections and writer lock | `db/connection.py`, `tests/db/test_connection.py` | `open_writer(path) -> sqlite3.Connection` (WAL, FULL, FK on); `open_reader(path)` (`query_only`); `class WriterLock` context manager over `fcntl.flock(LOCK_EX\|LOCK_NB)` raising `WriterBusy` | qwen | R | P1-2 |
| P1-4 | Migration runner with backup | `db/migrations.py`, `db/migrations/0001_initial.sql`, tests | `migrate(conn, db_path, backups_dir) -> int`; SQL from plan §5 verbatim; backup before applying; newer DB → `SchemaTooNew`; idempotent | qwen | R | P1-3 |
| P1-5 | paths.py: safe relative paths | `paths.py`, `tests/test_paths.py` | `path_key(rel: str) -> str`; `validate_relative(rel: str) -> PurePosixPath` (rejects abs, `..`, empty, NUL, segment > 120, total > 400); `resolve_target(root: Path, rel: str) -> Path` (lstat each existing component, no symlinks, realpath inside root); `is_case_only(a, b) -> bool` | qwen | R | P0-END |
| P1-6 | fsops: no-replace primitives | `fsops/primitives.py`, `fsops/errno_map.py`, `tests/fsops/` | `rename_noreplace(src, dst)` (renameat2 / renamex_np via ctypes; `DestinationExists`, `UnsupportedPlatform`); `fsync_dir`, `fsync_file`, `mkdir_one`, `rmdir_if_empty -> bool`, `copy_new(src, dst)` with `O_EXCL`, `discard_temp(work_dir, path)`, `entry_exists(parent, name)`, `same_device(*paths)`; `OM_FS_TEST_DIR` override | **opus** | R (**fable**) | P0-END |
| P1-7 | fsops: `FsOps` protocol and source-grep test | `fsops/protocol.py`, `tests/test_no_unsafe_calls.py` | `class FsOps(Protocol)` with the P1-6 functions; `RealFs`; grep test from plan §6.1 | qwen | R | P1-6 |
| P1-8 | Files repository: insert, get, page | `db/files_repo.py`, tests | `FilesRepo(conn)`: `insert_scanned(rec: FileRecord, now: str) -> int`, `get(file_id) -> FileRow \| None`, `page(offset, limit) -> list[FileRow]`, `count() -> int`; `FileRow` frozen dataclass | qwen | | P1-4 |
| P1-9 | Files repository: compare-and-set path update | `db/files_repo.py` or `db/files_write.py`, tests | `update_path(file_id, expect_row_version, new_path, size, mtime_ns, now) -> None`, raising `StaleRow`; unique `path_key` violation → `Collision` | qwen | R | P1-8 |
| P1-10 | Operation log repository | `ops/oplog_repo.py`, `ops/states.py`, tests | `ALLOWED: dict[tuple[str,str], frozenset[str]]` (kind, from) → to; `create_batch`, `add_op`, `transition(op_id, to, params=None, error=None)` rejecting illegal transitions; `active_ops() -> list[Operation]` | qwen | R | P1-4 |
| P1-11 | JSONL operation mirror | `ops/mirror.py`, tests | `append(work_dir, record: Mapping) -> None` (one line, fsync); called by `transition` through an injected callable | qwen | R | P1-10 |
| P1-12 | Crash-test support | `tests/support/faulty_fs.py`, `tests/support/invariants.py` | `SimulatedCrash(BaseException)`; `FaultyFs(inner, crash_at: int, when: "before"\|"after")`; `assert_consistent(root, conn, work_dir, original_hashes)` | qwen | R | P1-7 |
| P1-13 | Move op execution | `ops/move.py`, `ops/context.py`, tests | `OpContext` frozen (root, work_dir, fs, oplog, files, clock); `run_move(op, ctx) -> Operation` per plan §6.2; tests: happy path, collision, precondition failed, case-only, crash matrix | qwen | R | P1-9, P1-10, P1-12 |
| P1-14 | Move recovery | `ops/recover_move.py`, tests | `recover_move(op, ctx) -> Operation` per the §6.2 recovery table; one test per row; crash matrix re-run through recovery | qwen | R | P1-13 |
| P1-15 | Recovery dispatcher | `ops/recover.py`, tests | `recover_all(ctx) -> RecoveryReport` over `active_ops()`; dispatch by kind | qwen | R | P1-14 |
| P1-16 | Stat-only scan into files | `scan/stat_scan.py`, tests | `scan_into(root, repo, now) -> int` inserting new rows only (tracer; reconciliation is P2-5) | qwen | | P1-8 |
| P1-17 | Web app factory, healthz, file list | `web/app.py`, `web/routes_files.py`, `web/templates/{base,files}.html`, `web/static/htmx.min.js`, tests | `create_app(config) -> FastAPI`; `GET /healthz`; `GET /files?page=` (100 per page) | qwen | | P1-16 |
| P1-18 | Rename one file from the UI | `web/routes_rename_one.py`, template, tests | Form: new filename → draft batch with one move → confirm runs `run_move` synchronously; tracer binds 127.0.0.1 only, no auth yet | qwen | R | P1-15, P1-17 |
| P1-19 | CLI `serve` and `recover` | `cli.py`/`cli_commands.py`, tests | `serve` takes the WriterLock, migrates, recovers, starts uvicorn; `recover` runs `recover_all` and prints the report | qwen | R | P1-18 |
| P1-20 | Tracer E2E on the Mac | `scripts/tracer_e2e.sh` | Temp library from fixtures; serve; rename via HTTP; `kill -9` during an injected sleep (`OM_FAULT_SLEEP_AFTER=intent`); restart; assert recovered and consistent | **opus** | | P1-19 |
| P1-21 | Tracer on the Pi with throwaway copies | none (runbook in issue) | Deploy; copy 20 files to `…/_om_tracer/` on the SSD; `OM_FS_TEST_DIR=… pytest tests/fsops`; run the tracer script there; record kernel version, renameat2 result, dir-fsync result, FTS5 availability | **owner+opus** | | P1-20 |

## Phase 2: Foundations (epic)

| Id | Title | Files | Model | R | Depends |
|----|-------|-------|-------|---|---------|
| P2-1 | Error taxonomy | `errors.py`: `AppError(code, message, detail)`, `ErrorCode` StrEnum (plan §8), `STOPS_BATCH`; `fsops/errno_map.py` uses it | qwen | | P1-END |
| P2-2 | Error → HTTP mapping and envelope | `web/errors.py`: exception handlers, `envelope(ok, data, error)`, the no-`pass`-in-except test | qwen | | P2-1 |
| P2-3 | Jobs repository | `db/jobs_repo.py`: `enqueue`, `claim_next`, `progress`, `finish`, `request_cancel`, `mark_interrupted_on_startup` | qwen | | P2-1 |
| P2-4 | Single job worker with preemption | `jobs/worker.py`: `JobWorker(db_path, handlers: Mapping[str, Handler])`, `start()`, `stop()`; `Handler = Callable[[JobContext], JobResult]`; `JobContext.should_yield()`, `.cancelled()` | qwen | R | P2-3 |
| P2-5 | Reconcile diff (pure) | `scan/reconcile.py`: `diff(disk: Sequence[FileRecord], rows: Sequence[FileRow]) -> list[Action]` per plan §7 | qwen | R | P1-END |
| P2-6 | Scan job: stat, reconcile, read tags | `scan/scan_job.py`: indexes audio (`kind='audio'`) and art (`kind='art'`, no tags; whole-file hash in P3-4); applies the P2-5 actions, reads tags via `pipeline.read_result` and `metadata.interpret`, commits every 200, yields | qwen | R | P2-4, P2-5 |
| P2-7 | Library query: sort, filter, page | `db/files_query.py`: `FileQuery` frozen (sort enum, dir, status, ext, missing_field, folder), `query(conn, q, offset, limit)`, `count(conn, q)` | qwen | | P1-END |
| P2-8 | FTS search | `db/search.py`: FTS triggers present (from 0001), `match_expr(user_text) -> str` escaping, used by `files_query` | qwen | | P2-7 |
| P2-9 | Auth: password and session | `web/auth.py`, CLI `set-password`: scrypt hash in `state/auth.json` 0600, login, logout, rate limit | qwen | R (**opus** security) | P2-2 |
| P2-10 | CSRF, Host allowlist, Origin check | `web/csrf.py`, `web/hosts.py`: middleware and tests from plan §9.4 | qwen | R (**opus** security) | P2-9 |
| P2-11 | Library page: filters, sort, paging, search | `web/routes_files.py`, `templates/files.html` | qwen | | P2-8, P2-10 |
| P2-12 | Jobs page with progress and cancel | `web/routes_jobs.py`, `templates/jobs.html` | qwen | | P2-4, P2-10 |
| P2-13 | DB backup command | `db/backup.py`: `backup(conn, dest_dir, keep=14) -> Path`; CLI `db backup` | qwen | | P1-END |

## Phase 3: Hashing and duplicates (epic; `8su` rewritten as the parent)

| Id | Title | Files | Model | R | Depends |
|----|-------|-------|-------|---|---------|
| P3-1 | mp3 payload range | `audiohash/mp3_range.py`: `payload_range(head: bytes, tail: bytes, size: int) -> tuple[int,int]` (ID3v2 + footer, ID3v1, APEv2) | qwen | R | P2-END |
| P3-2 | m4a mdat ranges | `audiohash/mp4_ranges.py`: `mdat_ranges(read_at: Callable[[int,int], bytes], size: int) -> list[tuple[int,int]]` (64-bit sizes, size 0 = to EOF) | qwen | R | P2-END |
| P3-3 | Audio hasher | `audiohash/hasher.py`: `audio_hash(path, ext) -> tuple[str, Literal["audio","file"]]` BLAKE2b-128; test: same audio, different tags → same hash | qwen | R | P3-1, P3-2 |
| P3-4 | Hash job | `scan/hash_job.py`: hashes stale or missing stamps, commits every 200, yields | qwen | | P3-3, P2-6 |
| P3-5 | Duplicate groups query | `db/dupes_query.py`: groups paged by reclaimable bytes | qwen | | P3-4 |
| P3-6 | Duplicates page | `web/routes_dupes.py`, template | qwen | | P3-5, P2-11 |

## Phase 4: Pattern rename and move (epic; supersedes `dpf`, `cvf`, `z80`)

| Id | Title | Files | Model | R | Depends |
|----|-------|-------|-------|---|---------|
| P4-1 | Naming vocabulary | `naming.py` (or `naming_vocab.py`): placeholders; number-prefix rules N1–N5 quoted verbatim from plan C6 (takes `multi_disc_albums: frozenset[tuple[str,str]]` as input), with one test per rule plus `2-01` single-song disc and no-track-no-disc cases; Unknown_ substitutes; caps; unknown placeholder → `InvalidTemplate` (plan C6) | qwen | | P3-END |
| P4-1a | Multi-disc album query | `db/albums_query.py`: `multi_disc_albums(conn) -> frozenset[tuple[str, str]]` (album artist, else artist; album) for present audio files with disc total > 1 in raw tags or disc ≥ 2 (plan C6 rule N3) | qwen | | P4-1 |
| P4-2 | Pattern planner (pure) | `ops/plan_pattern.py`: `plan_pattern(rows, template, overrides, taken_keys) -> list[PlannedUnit]` with statuses ok, unchanged, renamed_copy, invalid; within-batch and case-only handling | qwen | R | P4-1, P4-1a |
| P4-2a | Collision suffixer (pure) | `ops/copy_suffix.py`: `assign_suffixes(claims: Sequence[Claim], taken_keys: Set[str]) -> dict[int, str]` per plan C5 (existing file keeps the name; then bitrate desc; then lowest file_id; lowest free N); used by P4-2 | qwen | R | P4-1 |
| P4-2b | Art follows audio planner (pure) | `ops/plan_art.py`: `plan_art(audio_units, folder_audio_counts, art_rows, taken_keys) -> list[PlannedUnit]` per plan §6.8 (move only when no audio is left; majority destination; root art never moves; identical → purge folder at its original relative path, different → `-copy-N`) | qwen | R | P4-2, P4-2a |
| P4-3 | Selection snapshots | `db/selections.py`: `create(conn, ids \| FileQuery) -> str`, `ids(conn, snapshot_id)` | qwen | | P3-END |
| P4-4 | Batch runner: units, stop rules, cancel | `ops/batch_runner.py`: `run_batch(batch_id, ctx, job) -> BatchResult`; registered as the `batch` job handler; art units run after their folder's audio units and are skipped if any failed | qwen | R | P4-2b |
| P4-5 | Emptied-folder cleanup after commit | `ops/dirs.py`: `cleanup_parents(root, rel_dir, fs) -> list[str]`, rmdir only, stops at the root | qwen | R | P4-4 |
| P4-6 | Rename-by-pattern preview and confirm pages | `web/routes_rename.py`, templates; replaces the P1-18 page | qwen | | P4-3, P4-4 |
| P4-7 | Pi check: pattern move of throwaway copies | runbook: includes a folder with `cover.jpg`, a `-copy-N` collision, a two-disc album where disc 2 has one song | **owner+opus** | | P4-6 |

## Phase 5: Metadata editing (epic)

| Id | Title | Files | Model | R | Depends |
|----|-------|-------|-------|---|---------|
| P5-1 | Tag writer | `tags/writer.py`: `write_fields(path, changes: Mapping[str, str\|int\|None]) -> None`, `SUPPORTED_EXTS = {"mp3","m4a"}`, keeps the ID3 version; test: P3-3 hash unchanged after write | qwen | R | P4-END |
| P5-2 | Free-space check | `fsops/space.py`: `require_free(path, needed_bytes, reserve=256 MiB)` → `OUT_OF_SPACE` | qwen | | P4-END |
| P5-3 | Retag op execution | `ops/retag.py`: `run_retag(op, ctx) -> Operation` per plan §6.3; original goes to `purge_dir/<relative path>` (with `-copy-N` via P4-2a); crash matrix | qwen | R | P5-1, P5-2 |
| P5-4 | Retag recovery | `ops/recover_retag.py` per the §6.3 table; register in `recover_all` | qwen | R | P5-3 |
| P5-5 | Edit planner (pure) | `ops/plan_edit.py`: `plan_edit(rows, field, value, repath_template \| None) -> list[PlannedUnit]` (unsupported, unchanged, re-path only when the file matches the template, Q-8) | qwen | R | P5-3 |
| P5-6 | Batch runner handles retag-then-move units | `ops/batch_runner.py` extension and tests | qwen | R | P5-4, P5-5 |
| P5-7 | Edit-field preview and confirm pages | `web/routes_edit.py`, templates | qwen | | P5-6 |
| P5-8 | Pi check: retag throwaway copies | runbook: hash unchanged; plays in a player; iTunes-tagged sample | **owner+opus** | | P5-7 |

## Phase 6: Undo (epic)

| Id | Title | Files | Model | R | Depends |
|----|-------|-------|-------|---|---------|
| P6-1 | Undo planner (pure) | `ops/plan_undo.py`: `plan_undo(committed_ops, file_filter=None) -> list[PlannedUnit]` per plan §6.7 | qwen | R | P5-END |
| P6-2 | History query | `db/history_query.py`: ops and events for a file, ordered | qwen | | P5-END |
| P6-3 | Batch history and undo pages | `web/routes_history.py`, templates | qwen | | P6-1, P6-2 |
| P6-4 | File detail page with history | `web/routes_file_detail.py`, template | qwen | | P6-2 |

## Phase 7: Drift and recovery UI (epic)

| Id | Title | Files | Model | R | Depends |
|----|-------|-------|-------|---|---------|
| P7-1 | Drift page and forget action | `web/routes_drift.py`, `db/drift_query.py` | qwen | | P6-END |
| P7-2 | Recovery page for needs_attention | `web/routes_recovery.py` (read-only plus "re-run recovery" job) | qwen | | P6-END |
| P7-3 | Status banner | `web/banner.py`: not mounted, mutations disabled, recovery needed, unclean-shutdown fsck hint | qwen | | P7-2 |

## Phase 8: Deployment (epic)

| Id | Title | Files | Model | R | Depends |
|----|-------|-------|-------|---|---------|
| P8-1 | systemd user units | `deploy/organize-music.service`, `deploy/organize-music-backup.{service,timer}` | qwen | | P7-END |
| P8-2 | Deploy script: stop, back up, migrate, start, healthz | `scripts/deploy_to_pi.sh` | qwen | R (**opus**) | P8-1 |
| P8-3 | Re-point or retire the legacy CLI commands | `cli*.py`; `meta`, `hash`, `dupes`, `tags` read from `library.db`, or are removed per owner | qwen | | P7-END |
| P8-4 | First real-library run, read-only | runbook: scan and hash the real library with `mutations_enabled: false` | **owner+opus** | | P8-2, P8-3 |
| P8-5 | Open the real-library gate | runbook: owner review, enable mutations, one-album rename and undo | **owner+opus** | | P8-4, P8-END |

## Phase 9: Later (epic)
`cpc` (rewritten: quarantine batch kind, depends on P4-4 and P3-5), `hpg`, `p1b`, and a new
"byte-exact restore from the purge folder" issue, all P3 or lower. There is no purge command:
the owner empties the purge folder by hand (plan §6.9).

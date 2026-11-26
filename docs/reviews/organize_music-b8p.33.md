# Review: CLI serve and recover commands (b8p.32)

Paired review of `organize_music-b8p.32` (the `serve` and `recover` CLI
commands, plan §6.4 "One writer"/"Startup":
`src/organize_music/cli_serve.py` (new, 165 lines), the `serve`/`recover`
subcommand wiring in `src/organize_music/cli.py` (+11), and
`tests/test_cli_serve.py` (new, 286 lines); PR #76, rebase-merged as
`1ce1f74` on 2026-11-26). The review target is the code as it is on
`origin/main` (`1ce1f74`). Catalogue id P1-19-R.

Reviewer: Hermes run `20261126_153624_ffc276` (model
Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed). The issue carries the label
`model:opus-5.5`; this run used Qwen3.8-27B, so the verdict is offered for
the human reviewer to confirm under the intended model, not as a binding
Opus sign-off (recorded below as finding F-3, not a code finding). Same
situation as the b8p.25 review (its F-3), the b8p.27 review (its F-2) and
the b8p.31 review (its F-4).

## Verdict

**Approve.** No safety findings: the CLI module makes no filesystem calls
of its own (guard + diff search below), every library disk change it
triggers happens inside the already-reviewed, already-matrixed
`recover_move`/`run_move` with preconditions first, and the lock semantics
are exactly the plan's. One **P2 functional** finding (F-1): `serve` holds
the writer lock for the server's lifetime while the tracer's synchronous
confirm re-takes that same lock, so under `serve` every web confirm is a
503 `WRITER_BUSY` — the tracer's only mutation flow is unusable under the
only way to start the server, and the P1-20 E2E procedure ("serve; rename
via HTTP") cannot pass. Verified end-to-end by probe in this run; filed as
a new P2 issue (discovered-from `organize_music-b8p.33`). One P3 finding
(F-2: the "serving read-only" announcement vs. the app's missing
`LIBRARY_NOT_MOUNTED` mutation gate). None is a safety finding; F-1
blocks the P1-20 E2E *procedure* (b8p.34) and is flagged for the owner
(see "Blocking" below).

## What the code does (and how it maps to the plan and the contract)

`run_serve(config)` (`cli_serve.py:112-136`): `mkdir state_dir`, then
`with WriterLock(state_dir/'writer.lock'):` → `open_writer(state_dir/
'library.db')` → `_migrate` (a `SchemaTooNew` prints `error: …` and exits
2) → `_recover` (when `_library_root` reports mounted: `recover_all` on a
production `OpContext` — `RealFs`, JSONL mirror, live clock — and print
`recover: committed N, failed M; needs attention: ids`; else print
`library not mounted: serving read-only (LIBRARY_NOT_MOUNTED)`) →
`uvicorn.run(create_app(config), host=config.bind_host,
port=config.bind_port, workers=1)` (blocks inside the lock; released when
the server stops) → exit 0. `WriterBusy` → print its message, exit 2.
`run_recover` (`:139-165`) is the same preamble minus the server: exits 1
when the library is not mounted (nothing could be verified) or when any op
ended `needs_attention`, else 0; exit 2 when locked or schema too new.
`_library_root` (`:56-66`) is the contract's mounted check verbatim
(`config.library` exists **and** `os.path.ismount(config.library_mount)`).

Line-by-line against b8p.32's "What to do" and plan §6.4
(`WEB_UI_PLAN.md:401-405` One writer, `:409-411` Startup, `:425-427`
Mounted check):

| Contract element | Code | Match |
|---|---|---|
| "serve -> with WriterLock(state_dir/'writer.lock'): open_writer(state_dir/'library.db')" | `cli_serve.py:112-125` — `with WriterLock(config.state_dir / "writer.lock")` then `open_writer(db_path)`; the help string says so too (`cli.py:84`) | ✓ |
| "migrate" (under the held lock) | `:126` → `_migrate` (`:101-109`): `migrate(conn, db_path, state_dir/'backups', now)`; `SchemaTooNew` → printed error, exit 2 (docstring `:143-146`) | ✓ |
| "if library mounted run recover_all and print the report" | `:127-129` → `_recover` (`:87-98`): `_library_root` None → `None` (skip, print the read-only line at `:128`); else `recover_all(_op_context(...))` + `_say(_render_report(report))` (`:68-70`) | ✓ |
| "then uvicorn.run(create_app(config), host=config.bind_host, port=config.bind_port, workers=1)" | `:130-131` — exactly those arguments, `workers=1`, `create_app(config)` from `web/app.py` | ✓ |
| "recover -> same lock, migrate, recover_all, print report, exit 0 (1 if any needs_attention)" | `:139-165` — same lock/migrate preamble; `report.needs_attention` empty → `EXIT_OK` else `EXIT_NEEDS_ATTENTION` (`:165`); 2 when locked (`:156-158`) or schema too new | ✓ (the not-mounted → exit 1 addition is plan-conformant: Startup, `:409-411`, recovery "waits with LIBRARY_NOT_MOUNTED"; documented in the docstring `:145`) |
| "Library-mounted check: os.path.ismount(config.library_mount) and config.library.is_dir()" | `_library_root` (`:56-66`): `config.library is None or not config.library.is_dir()` → `None`; else `config.library if os.path.ismount(config.library_mount) else None` — same two conditions (order swapped, no behavioral difference) plus the `None` guard | ✓ |
| "No systemd (P8-1)" | no systemd units or references in the diff | ✓ |
| "Files: cli.py, cli_commands.py (or cli_serve.py if over 200 lines)" | `cli_commands.py` is 123 lines; adding both commands (~170 lines) would breach the 200-line rule, so the sanctioned split is used: new `cli_serve.py` (165), `cli.py` gains only the two subparsers (+11, 109 total) | ✓ |
| Plan §6.4 One writer: CLI writers "fail with 'server is running' if they can't get it" | `WriterBusy` carries exactly `"server is running"` (`db/connection.py:64`); both commands print it and exit 2; locked-in by `test_recover_held_lock_exits_2_server_running` (`test_cli_serve.py:152-163`) and `test_serve_held_lock_exits_2_and_starts_nothing` (`:166-181`) | ✓ |

No drift from the contract. Two deliberate, documented extensions of its
letter: (1) a `SchemaTooNew` during the preamble exits 2 (the constant is
named `EXIT_LOCKED` — observation 1 below); (2) `recover` exits 1 (not 0)
when the library is not mounted, so a skipped pass is never reported as
success. Both are documented in the module/function docstrings and match
the plan's semantics.

## Checklist (every item answered, with evidence)

- **Read the plan sections quoted in organize_music-b8p.32 and compared
  the code line by line.** b8p.32's Design quotes plan §6.4 ("Startup and
  One writer"). This run read `WEB_UI_PLAN.md` §6.4 (`:381-411`, One
  writer `:401-405`, Startup `:409-411`), §6.5 Mounted check
  (`:425-427`) and §8 (error codes); the mapping table above covers the
  full b8p.32 contract with line references. The plan's `st_dev`
  equality of root/work/purge in the mounted check (`:425-427`) is not
  implemented — but b8p.32's contract pins the check to the two stated
  conditions (`ismount` + `is_dir`), so the simpler form is the contract
  here; the `st_dev` rule remains plan territory for the later batch
  runner (recorded, not a drift).

- **Every state transition has a crash-matrix test (FaultyFs before/after
  each fs call) followed by recovery and assert_consistent, where the
  module performs disk changes.** `cli_serve.py` performs **no filesystem
  calls at all** (no `fsops` import; the only `os` use is the read-only
  `os.path.ismount` probe at `:65`). Its durable writes are SQLite:
  `open_writer` (WAL/FULL), `migrate` (backup + apply — its crash matrix
  is committed from `organize_music-3yw`) and the oplog transitions inside
  `recover_all` (one atomic transaction each: rollback + no mirror on
  failure, `oplog_repo.py:127-164`; the mirror append is fsynced per line
  and **raises** on failure — loud, not swallowed, `ops/mirror.py:43-46`).
  There is no multi-step fs sequence in this module to matrix. The
  disk-changing code it drives is the already-reviewed
  `recover_move` (b8p.25: committed crash matrix in
  `tests/ops/test_recover_move.py`; its committed torn-recovery-test gap is
  the already-filed `organize_music-6yg`) dispatched through
  `recover_all` (b8p.27; its committed torn-pass-test gap is the
  already-filed `organize_music-h1e`). Nothing new to matrix here.

- **No code path can replace or delete a library file.**
  `pytest -q tests/test_no_unsafe_calls.py tests/test_file_length.py` →
  **4 passed** (part of the 499). A hand search of the PR #76 diff
  (`git diff 04bda74..1ce1f74`, added lines) over the guard's own patterns
  (`os.rename(`, `os.replace(`, `os.remove(`, `os.unlink(`,
  `shutil.move(`, `shutil.rmtree(`, `.rename(`, `.replace(`, `.unlink(`)
  returned **one match, in the test file**: `(env.root / REL).unlink()`
  (`test_cli_serve.py:196`) — fixture setup deleting its own tmp file to
  build the crashed-move picture, not a library-file call; **zero in
  src/**. The only "move" in src/ is the op-kind string and the
  `recover_move` dispatch (already cleared in b8p.23/b8p.25).

- **Preconditions (path, size, mtime_ns, row_version) are checked before
  the first disk change.** The CLI's own disk touches are scratch:
  `state_dir.mkdir` (`:117, :144`), `open_writer` and `migrate` on
  `library.db` (state, not the library) and its backup — none act on
  library files, so no precondition is needed for them. The first
  **library** disk change happens inside the code this module dispatches
  to, and both check first: `recover_move` samples the disk read-only
  (`entry_exists` ×3, `recover_move.py:52-54`) and verifies the
  destination's size + `mtime_ns` before its first DB write
  (`:92-94`); `run_move`'s planned step re-stats and re-reads
  `row_version` before its first action (`move.py:59-90`, b8p.23). The
  CLI additionally gates the whole recovery on the mounted check
  (`_library_root`, `:56-66`) before any library access — an unmounted
  library cannot be touched by the CLI at all (`test_cli_serve.py:228-242`
  locks this in: no recovery, no report, op left `applied`).

- **Errors are explicit and use the documented codes; no bare `except`, no
  `except: pass`, nothing swallowed.** Three `except` clauses in the new
  file (grep): `SchemaTooNew` (`:106`) → printed `error: {exc}` + exit 2;
  `WriterBusy` (`:131`, `:156`) → printed message ("server is running",
  `connection.py:64`) + exit 2. No bare `except`, no `except: pass`
  anywhere in the diff. Unexpected errors (other `sqlite3.Error`,
  `OSError`, anything `recover_all` raises) propagate as tracebacks —
  loud, not swallowed — and leave every op at its last durable state
  (`recover_move`'s contract), so the next run retries. Exit-code
  vocabulary: 0 = ok, 1 = needs attention / not mounted, 2 = locked or
  schema too new or (per `cli.py:20`) usage — documented in the
  docstrings (`:4-17, :139-147`).

- **Tests were written first and cover the failure cases listed in
  b8p.32.** b8p.32's notes record the TDD order: "PROGRESS: tests written
  (8, red) and passing (green); quality gate green (… pytest 499 passed)".
  All three cases b8p.32 listed to write first are present in
  `tests/test_cli_serve.py`: recover with a held lock exits 2 with
  "server is running" (`:152-163`); recover over a DB with one
  interrupted move commits it and prints the count, and a second pass is a
  no-op (`:184-209`); serve with `uvicorn.run` monkeypatched receives the
  config's bind host/port and `workers=1` and the real app over the
  configured database (`:255-271`). Five more are committed: serve with a
  held lock exits 2 and never reaches uvicorn (`:166-181`); an unknown
  kind left `applied` ends `needs_attention` and the command exits 1
  (`:212-225`); an unmounted library skips recovery, exits 1 and prints
  `LIBRARY_NOT_MOUNTED` (`:228-242`); no active ops → exit 0 with
  `committed 0` (`:245-252`); an unmounted library still serves
  (`:274-286`). The true before/after-`FaultyFs` sweep of the disk steps
  lives in the move/recovery matrices (second checklist item).

- **Files are <= 200 lines, typed signatures, no dead code.** `wc -l`:
  `cli_serve.py` **165**, `cli.py` **109**, `cli_commands.py` **123**
  (untouched); `tests/test_cli_serve.py` 286, outside the guard's scope
  (`tests/test_file_length.py` scans `src/organize_music` only; it passes
  in the gate below). Every signature is typed (`_library_root(config:
  Config) -> Path | None` `:56`, `_recover(config: Config, conn:
  sqlite3.Connection) -> RecoveryReport | None` `:87`,
  `run_serve(config: Config) -> int` `:112`,
  `run_recover(config: Config) -> int` `:139`, …). No dead code: all nine
  module-level names are used — `run_serve`/`run_recover` from
  `cli.py:16, :87, :91`, the six helpers from each other
  (`_library_root` ← `_recover`; `_op_context` ← `_recover`;
  `_render_report` ← `_recover`; `_migrate` ← both entry points;
  `_utcnow` ← `_migrate` and `_op_context`; `_say` ← all of them), and the
  three exit constants from both entry points.

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.33` (branched from `origin/main` `1ce1f74`), run
under the project venv (Python 3.13, ruff):

```
ruff check .          -> All checks passed!
ruff format --check . -> 130 files already formatted
pytest -q             -> 499 passed, 1 skipped, 4 warnings in 4.63s
```

The 1 skip is the case-sensitive-filesystem skip in
`tests/fsops/test_primitives.py:80` — pre-existing and unrelated. The 4
warnings are yoyo's deprecated default `datetime` adapter — pre-existing
and unrelated. `tests/test_cli_serve.py` (8),
`tests/test_no_unsafe_calls.py` and `tests/test_file_length.py` are all
green.

## Findings

- *F-1 (P2, functional — the served web UI can never confirm): `serve`
  holds the writer lock for the server's lifetime, and the tracer's
  synchronous confirm re-takes that same lock, so every confirm under
  `serve` is a 503 `WRITER_BUSY`.* `run_serve` takes
  `with WriterLock(...)` **around** `uvicorn.run(..., workers=1)`
  (`cli_serve.py:123-135`): with `workers=1` uvicorn 0.54.0 runs
  in-process (verified from the installed source: `run()` forks a
  `Multiprocess` only when `workers > 1` or reload is on, otherwise
  `server.run()` in the same process), so the app serves inside the
  process that holds the lock. `WriterLock` is a non-blocking
  `fcntl.flock` (`db/connection.py:47-78`), and `flock` locks are per
  open file description: this run probed that a second `WriterLock` on
  the same path in the same process raises
  `WriterBusy("server is running")` (`/tmp/probe_b8p33_lock.py`). The
  tracer's confirm re-takes the lock per request
  (`rename_confirm.py:67-71` — the b8p.30 synchronous stand-in for the
  plan's job worker; b8p.31's review reviewed the confirm in isolation,
  before `serve` existed, so no earlier review saw the combination).
  End-to-end probe in this run (`/tmp/probe_b8p33_e2e.py`): preview
  200 + draft batch 1; with the lock held, `POST /batches/1/confirm`
  → **HTTP 503, page carries `WRITER_BUSY`**, draft survives, nothing on
  disk changed; lock released (server stopped) → the same confirm
  returns 200 and commits the rename. So under `organize-music serve`
  — the **only** way to start the server (the `organize-music` entry
  point is the sole launcher; `pyproject.toml` `[project.scripts]`) — the
  user can browse and preview but can **never confirm**: the tracer's
  only mutation flow is permanently dead, and the P1-20 E2E procedure
  ("serve; rename via HTTP; kill -9; restart", catalogue row P1-20
  `WEB_UI_ISSUES.md:62`, bead `organize_music-b8p.34`) cannot pass.
  Root cause: the plan's "One writer" model (`WEB_UI_PLAN.md:401-405`)
  has the in-process writer (the job worker) **own** the write connection
  and HTTP handlers only enqueue — in-process writers never re-acquire
  the process-wide lock; the tracer's synchronous confirm does. **Not a
  safety finding: the request is refused before any write, the draft is
  not consumed (the delete happens after the lock,
  `rename_confirm.py:100`), the server's lock release restores
  everything, and no state is corrupted. Filed: P2
  `organize_music-rst` (discovered-from `organize_music-b8p.33`).
- *F-2 (P3, plan deviation / misleading message): `serve` announces
  "serving read-only" but the app enforces no `LIBRARY_NOT_MOUNTED`
  mutation gate.* `cli_serve.py:127-128` prints
  "library not mounted: serving read-only (LIBRARY_NOT_MOUNTED)", and
  plan §6.4 Startup (`WEB_UI_PLAN.md:409-411`) says "the server starts
  read-only, and every mutation and recovery waits with
  `LIBRARY_NOT_MOUNTED`". Nothing in the app implements that gate:
  `LIBRARY_NOT_MOUNTED` appears in `src/` **only** in `cli_serve.py`
  (grep); the confirm guards check `mutations_enabled`, a configured
  `library_root` and the database file's existence
  (`rename_confirm.py:60-66`) but not the mount state, and `/healthz`
  uses `ismount` for its probe only (`app.py:73-83`). Consequences: with
  the library directory present but unmounted, a confirm proceeds into
  `run_move` — the common case (the mount-point folder is empty after
  unmount) dies at the source `stat` and the op fails
  `PRECONDITION_FAILED` (safe, but the wrong code and a misleading page),
  and the edge case (stale content under the unmounted path) renames
  against the wrong location. The fix must also distinguish the Pi's
  "configured mount point, currently unmounted" (gate) from a dev layout
  where `library_mount` is an ordinary directory (`os.path.ismount` is
  always False for one — every existing web test uses such a directory),
  or the local development UI would be permanently non-mutating. Not a
  safety finding (the precondition check fails first in the common case).
  Filed: P3 `organize_music-0u3` (discovered-from
  `organize_music-b8p.33`).
- *F-3 (process): model label.* The issue is labelled `model:opus-5.5`
  (the intended paired reviewer), but this run was performed under
  Qwen3.8-27B (MTPLX-Optimized-Speed), exactly as the b8p.25, b8p.27 and
  b8p.31 reviews were. The findings above are mechanical (contract
  mapping, proven guard, diff search, and two executable probes), so they
  are model-independent; the label is recorded here so the sign-off is
  not mistaken for an Opus one. Not a code finding and not a blocker.

Observations (not filed): (1) a `SchemaTooNew` during the preamble exits
2 through the constant named `EXIT_LOCKED` (`cli_serve.py:40, :107-110,
:152`) — exit 2 therefore doubles as "locked", "schema too new" and (per
`cli.py:20` `EXIT_USAGE = 2`) usage error; the stderr message is the only
distinguisher. This is consistent with the CLI's existing 2-for-errors
convention and documented in `run_recover`'s docstring
(`:143-146`), so it is recorded, not a finding. (2) The plan's One-writer
bullet names `db migrate` as a CLI writer that takes the lock
(`WEB_UI_PLAN.md:401-405`); no `db migrate` subcommand exists yet —
`migrate()` is a library function that `serve`/`recover`/confirm already
run under the lock, and b8p.32's contract asks only for `serve`+
`recover`, so this is a later-phase line, not a drift. (3)
`workers=1` is load-bearing for the lock model (the probe above: only
`workers > 1` or reload forks); the contract pins it and
`test_serve_receives_config_bind_host_port_and_one_worker`
(`test_cli_serve.py:255-271`) locks it in.

## Blocking

F-1 is a functional (not safety) finding, so nothing is force-blocked by
this review under the "safety findings block the next phase" rule. But F-1
makes the *documented procedure* of `organize_music-b8p.34` (P1-20
"Tracer E2E on the Mac": serve → rename via HTTP) impossible until it is
fixed, and this review issue may not edit the graph of an unclaimed bead,
so no dependency edge was added. **Owner: gate b8p.34 on
`organize_music-rst`** (or re-scope its procedure to a non-serve
startup) before the next run picks it up.

## Duplicate check

`bd list --all` (206 issues, checked at `origin/main` `1ce1f74`):
`organize_music-b8p.3`/`b8p.4` (closed) cover the lock primitive itself;
`organize_music-y4y` (closed) fixed its fd leak; `organize_music-g5v`
(closed) fixed the `/healthz` mount probe; `organize_music-5yw`/`y8t`/
`0tc` (open, from the b8p.31 review) cover the confirm's batch
settlement, the unlogged reader probe / code vocabulary, and the NFC
storage — different files and gaps than F-1/F-2. No open issue covers the
serve-held-lock vs. confirm-re-takes-lock collision, or the
read-only-announcement gap: two new issues are filed and no duplicate
exists.

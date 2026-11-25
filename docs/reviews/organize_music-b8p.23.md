# Review: Move operation execution (b8p.22)

Paired review of `organize_music-b8p.22` (the journaled move operation, plan
§6.2: `ops/context.py`, `ops/move.py`, `tests/ops/test_move.py`, PR #59,
feature commit `b4aff61` plus the case-insensitivity fix `e845703` pushed as
review-fix `organize_music-225`). The review target is the code as it is on
`origin/main` `f803732` after b8p.22 landed. Catalogue id P1-13-R.

Reviewer: Hermes run `20261124_213339_455d07` (model
Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed). The issue carries the label
`model:opus-5.5`; this run used Qwen3.8-27B, so the verdict is offered for the
human reviewer to confirm under the intended model, not as a binding Opus
sign-off (flagged below as finding F-4, not a code finding).

## Verdict

**Approve.** No safety findings, nothing blocks the next phase (b8p.24
"Move recovery" and b8p.36 "End-of-phase review"), and three minor findings are filed as
`organize_music-fcj` (see "Findings"). The module matches
the plan §6.2 state table line by line; every disk action goes through the
fsops primitives (the no-unsafe-calls guard passes and is proven effective by
a plant in this run, and a hand search of the PR #59 diff found zero raw
replace/delete calls); preconditions are re-checked before the first disk
change and re-guarded by compare-and-set at commit; the FaultyFs crash matrix
covers every filesystem call, before and after (14 crash points for the
new-subfolder move, 16 for the case-only rename), and asserts the core
safety invariant the plan promises: after a crash the file's content is at
exactly one of `{src, via, dst}` and is byte-identical. The one checklist
item that cannot be exercised yet — the *recovery + assert_consistent* half
of the crash matrix — is the next ticket (b8p.24), by design. Three minor,
non-blocking findings are filed as `organize_music-fcj` (P3); none blocks
the next phase.

## What the module does (and how it maps to plan §6.2)

`run_move(op, ctx)` (`move.py:38-45`) re-reads the op row and walks the §6.2
table `planned -> intent -> [staged] -> applied -> committed` in a loop
(`_step`, `move.py:48-56`), dispatching one handler per state. Each handler
ends in `OplogRepo.transition`, which is one durable transaction (transition
check, optional `extra` write on `files`, op-row update, commit, then the
JSONL mirror — `oplog_repo.py:127-164`), so every step is durable before the
next, exactly as plan §6.1 (`WEB_UI_PLAN.md:300-305`) requires.

| Plan §6.2 row (`WEB_UI_PLAN.md:327-333`) | Code | Match |
|---|---|---|
| planned: precondition check; validate dst (§9.4); dst free (DB `path_key` and `entry_exists`); same device; record folders | `_planned` `move.py:59-90`: `os.stat` of src, size+mtime_ns mismatch → `PRECONDITION_FAILED` + row marked `changed` (`:66-75`); `resolve_target` (`:80`, `paths.py:83-97` refuses symlinks/escapes); `_dst_taken` excludes the op's own file_id (`:81`, `:160-166`) then `fs.entry_exists` (`:83`); `fs.same_device` against the closest existing ancestor (`:85`, `:169-174`); `_missing_parents` parent-first into `params["created_dirs"]` (`:88-90`, `:177-185`) → `intent` | ✓ line by line |
| intent: `mkdir_one` each missing folder; `rename_noreplace(src, dst)` (or `src→via` for case-only); fsync both parents | `_intent` `move.py:93-110`: `mkdir_one` per `created_dirs` (`:99-100`); `via` set → `rename_noreplace(src, via)` + fsync both parents → `staged` (`:101-106`); else `rename_noreplace(src, dst)` + fsync both parents → `applied` (`:107-110`) | ✓ |
| staged: `rename_noreplace(via, dst)`; fsync parent | `_staged` `move.py:113-119` → `applied` | ✓ |
| applied: stat dst equals expected size and mtime; DB: `path`, `path_key`, `row_version+1`, op `committed` in one transaction | `_applied` `move.py:122-140`: `os.stat(dst)` mismatch → `needs_attention` (matches the plan's recovery-table row "✗ ✗ ✓ (mismatch) → needs_attention", `WEB_UI_PLAN.md:343`); match → `extra = files_write.update_path` (`:137-138`) run in the *same* transaction as the `committed` transition (`oplog_repo.py:151-159`), so the row CAS (`files_write.py:58-67`, `StaleRow`/`PathTaken`) and the op state commit atomically | ✓ |
| committed: `rmdir_if_empty` on each emptied source folder up to the library root (best effort, logged) | `_cleanup_empty_dirs` `move.py:143-157`: walks parents to (not including) root, `rmdir_if_empty` only removes empty directories (`primitives.py:127-139`), stops at the first non-removal | ✓ best effort; **no log line** (finding F-1) |

`plan_move_params` (`move.py:24-35`) returns exactly the plan's
`{src, dst, via, created_dirs, dst_root}` shape (`WEB_UI_PLAN.md:323-325`);
`via` is `<parent>/.om-<op_id>.tmp` in the source folder for case-only
renames and `None` otherwise — the plan's "work_dir-free" design. The
case-only path is what makes the `entry_exists` exact-name check
(`primitives.py:176-187`, plan §6.1 `:307-308`) work: at the `staged` step
the file sits at `via`, so the destination name is genuinely free, and on
case-insensitive exFAT the atomic `RENAME_NOREPLACE` in
`primitives.rename_noreplace` (`primitives.py:61-101`, including its
`lexists` pre-refusal, `:72-73`) is the final arbiter.

The engine's only error exits besides the durable `failed`/`needs_attention`
states are *uncaught* exceptions that propagate to the caller
(`DestinationExists`, `UnsupportedPlatform`, `OSError`, `IllegalTransition`,
`StaleRow`/`PathTaken`) — with the op left in its last durable state, the
crash-safe posture the plan specifies. Nothing in `move.py` is swallowed.

## Checklist (every item answered, with evidence)

- **Plan sections read; the code compared line by line.** Plan §6.1
  (`WEB_UI_PLAN.md:300-320`), §6.2 (`:322-345`, incl. the S/V/D recovery
  table), §6.5 durability (`:414-426`) were read; the mapping table above
  covers every §6.2 row against `move.py` with line references. No drift:
  states and edges in `states.py:19-29` for `move` are exactly the §6.2
  table plus the crash-recovery terminal edges (`failed`,
  `needs_attention`) already reviewed in b8p.17; `TERMINAL`/`ACTIVE`
  (`states.py:12-16`) are consistent with the oplog partial unique index.

- **Every state transition has a crash-matrix test (FaultyFs before/after
  each fs call), followed by recovery and assert_consistent.**
  `test_move_survives_a_crash_at_every_point`
  (`tests/ops/test_move.py:316-357`) measures the fs-call count of a clean
  run with `count_calls` (`:311-313`) and then crashes at *every* call,
  `before` and `after` (`FaultyFs`, `tests/support/faulty_fs.py:85-118`),
  parameterised over both move shapes (`:316-318`). This run measured the
  matrix: **7 fs calls → 14 crash points** for `a/one.mp3 → a/new/one.mp3`
  (2 planned checks, 4 intent, 1 cleanup) and **8 fs calls → 16 crash
  points** for the case-only `a/one.mp3 → a/One.mp3` (2 planned, 3 intent,
  2 staged, 1 cleanup) — 30 crash points, all passing. After each crash the
  test asserts the plan's core invariant: the content (deduplicated by
  `(st_dev, st_ino)` so the assertion stays honest on case-insensitive
  filesystems, `:337-352`) is at **exactly one** of `{src, via, dst}` and is
  byte-identical (`:353-357`). The *recovery + assert_consistent* half is
  not exercisable yet: recovery is the next ticket, `organize_music-b8p.24`
  "Move recovery" (blocked by this review), and the harness docstring
  (`faulty_fs.py:31-43`) already shows the full
  crash → `recover_move` → `assert_consistent` pattern that ticket will
  instantiate against the S/V/D table. Same staging as b8p.21 ("the matrix
  targets the not-yet-built layer"): the matrix that exists here proves the
  no-loss/no-duplication invariant at every crash point; the recovery
  decision table gets its own crash tests in b8p.24.

- **No code path can replace or delete a library file.**
  `pytest -q tests/test_no_unsafe_calls.py` → **3 passed** (exit 0). The
  guard is proven effective in this run: an `os.remove("x")` planted at
  `src/organize_music/_probe_tmp.py` made
  `test_no_unsafe_filesystem_calls_outside_fsops` **fail**, and after
  removing the plant the file passed again (3 passed). A hand search of the
  PR #59 diff (`gh pr diff 59`; exactly `ops/context.py`, `ops/move.py`,
  `tests/ops/test_move.py`, 25 075 chars) for
  `os.rename|os.replace|os.remove|os.unlink|shutil.move|shutil.rmtree|Path.rename|.unlink(|.replace(|os.rmdir`
  returned **0 matches** in added code. Every disk-mutating call in the
  added code goes through the fsops primitives: `ctx.fs.rename_noreplace`
  (×3, `move.py:103,107,117`), `ctx.fs.mkdir_one` (`:100`),
  `ctx.fs.fsync_dir` (×5), `ctx.fs.rmdir_if_empty` (`:152` — `os.rmdir`
  removes a *directory* and only when empty, `primitives.py:127-139`, so it
  cannot delete a file), plus read-only `os.stat` (`move.py:66,126`). The
  only `except` in `move.py` is the cleanup's
  `except OSError` (`:153-154`), which does not touch the filesystem and
  cannot catch `SimulatedCrash` (a `BaseException`, `faulty_fs.py:76`).

- **Preconditions (path, size, mtime_ns, row_version) are checked before the
  first disk change.** `_planned` (`move.py:59-90`) performs *no* disk
  change (only `stat`/`listdir`/DB reads); it re-stats the source
  (`:66-70`: `st_size`, `st_mtime_ns` against the op's `expect_*`) and
  re-reads the row (`:71-75`: status `present`, `row_version`) and fails
  with `PRECONDITION_FAILED` (row marked `changed`, `:68,70,75`) before
  the `planned → intent` transition; the first disk change
  (`mkdir_one`/`rename`) happens only in `_intent`. A crash between the
  check and the first change leaves the op `planned`, which is re-checked
  on re-run — the forward path has no check-then-act gap. At commit,
  `files_write.update_path` re-guards `row_version` and `status = 'present'`
  as a compare-and-set (`files_write.py:58-67`), so a row changed after the
  precondition is still refused (`StaleRow`).

- **Errors are explicit and use the documented codes; no bare `except`, no
  `except: pass`, nothing swallowed.** `move.py` has exactly one `except`
  clause — `except OSError: removed = False` in `_cleanup_empty_dirs`
  (`:153-154`), the plan-mandated best-effort cleanup
  (`WEB_UI_PLAN.md:333`), whose result (walk stops) is used; no bare
  `except`, no `except: pass`. Durable failure codes written via `_fail`
  (`move.py:188-196`): `PRECONDITION_FAILED`, `COLLISION`, `CROSS_DEVICE`;
  plus `NEEDS_ATTENTION` from `_applied` (`:129`) — all explicit
  `(code, detail)` pairs stored on the op row. The one vocabulary deviation:
  `CROSS_DEVICE` is not in the plan's documented error-code list
  (`WEB_UI_PLAN.md:397-398` lists `LIBRARY_NOT_MOUNTED`, `OUT_OF_SPACE`,
  `IO_ERROR`, `INTERNAL`, `PERMISSION`, and §6.1's "same device" check
  names no code) — finding F-2, minor and defensive (unreachable once the
  §6.5 startup mounted-check holds). Everything else is either a plan
  code or a type/error raised from the already-reviewed
  `files_write`/`oplog`/`paths` modules and propagated, not caught.

- **Tests were written first and cover the failure cases listed in
  b8p.22 (collision, precondition failed, crash at each step).** b8p.22's
  notes record the TDD order ("PROGRESS: tests written (RED) then
  implemented") and list exactly the cases now in `tests/ops/test_move.py`
  (10 tests, **10 passed** in this run): `plan_move_params` shape and
  case-only `via` (`:177-191`); happy path into a new subfolder, including
  the emptied-source-folder cleanup (`:199-220`); collision on disk with
  both files untouched (`:228-240`) and collision in DB only
  (`:243-262`); precondition failure marking the row `changed`
  (`:270-282`); case-only rename through `staged`, asserted by exact
  `os.listdir` (`:290-303`, made case-insensitive-FS-agnostic by
  `e845703` after hermes-review's mechanical gate rejected PR #59 — the
  same tests pass in this case-sensitive sandbox); and the crash matrix
  (`:316-357`). RED evidence is the implementer's PROGRESS note (the test
  and implementation landed in one feature commit, as in every other
  reviewed ticket); the gate here is green, including the case-only
  parameter that previously failed.

- **Files are <= 200 lines, typed signatures, no dead code.**
  `wc -l`: `ops/move.py` **196**, `ops/context.py` **56**,
  `tests/ops/test_move.py` 357 (test files are outside the guard's scope —
  `tests/test_file_length.py` scans `src/organize_music` only, and
  `test_file_length` passes). Every public and private signature in
  `move.py`/`context.py` is typed (`plan_move_params(...) -> dict[str,
  object]`, `run_move(op: Operation, ctx: OpContext) -> Operation`, the
  `_step` handlers, `_fail`, `_dst_taken`, `_existing_ancestor`,
  `_missing_parents`, `OpContext` fields, both exception classes).
  **Dead code exists**: `PreconditionFailed` and `Collision`
  (`context.py:41-56`) are defined but never raised, imported, or asserted
  anywhere (grep over `src/` and `tests/` returns only the definitions),
  and the `context.py` module docstring (`:6-7`) claims they are "the two
  failure classes the engine raises" — the engine instead records `failed`
  states with error codes. Finding F-3, minor (the classes were required by
  b8p.22's spec; they are currently unimplemented vestiges).

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.23` (from `origin/main` `f803732`), run under the
project venv (Python 3.13, `requires-python >= 3.12`):

```
ruff check .          -> All checks passed!
ruff format --check . -> 113 files already formatted
pytest -q            -> 411 passed, 1 skipped, 4 warnings in 3.44s
```

The 1 skip is the case-sensitive-filesystem skip in
`tests/fsops/test_primitives.py` (case-only rename primitives; it runs on
the Pi's exFAT and on APFS) — unrelated to this review. The 4 warnings are
yoyo's deprecated default `datetime` adapter — pre-existing and unrelated.
`tests/ops/test_move.py` (10), `tests/test_no_unsafe_calls.py` (3, incl.
the plant proof above) and `tests/test_file_length.py` (1) are all green.

## Findings

None blocking. No safety findings: no path in the PR can replace or delete
a library file (guard + diff search above), preconditions precede the first
disk change and are re-guarded at commit, and the crash matrix proves
content survives at exactly one location at every crash point. One new
`organize_music-fcj` (P3, `discovered-from:organize_music-b8p.23`) bundles
the three minor findings below; none of them blocks b8p.24 or b8p.36.

- *F-1 (minor): the best-effort cleanup is not logged.* Plan §6.2
  (`WEB_UI_PLAN.md:333`) specifies the committed step as "best effort,
  **logged**"; `_cleanup_empty_dirs` (`move.py:143-157`) catches `OSError`
  silently (`:153-154`). The project already has a `logging` precedent
  (`db/migration_checksums.py:13,27`). Observability only — the walk still
  stops and the op is unaffected.
- *F-2 (minor): `CROSS_DEVICE` is not in the plan's documented error-code
  vocabulary.* `move.py:86` invents the code; §6.4
  (`WEB_UI_PLAN.md:397-398`) lists `LIBRARY_NOT_MOUNTED`, `OUT_OF_SPACE`,
  `IO_ERROR`, `INTERNAL`, `PERMISSION` and the §6.1 "same device" check
  names no code. Defensive (the §6.5 startup check makes it unreachable in
  a configured system) and the op fails cleanly with nothing moved; the
  fix is either documenting the code in the plan or reusing a documented
  one.
- *F-3 (minor): dead code in `ops/context.py`.* `PreconditionFailed`
  (`:41-47`) and `Collision` (`:50-56`) are never raised or imported; the
  module docstring (`:6-7`) misdescribes them as "the failure classes the
  engine raises". Either remove them (and fix the docstring) or wire the
  engine to raise them; removal is the smaller change and matches the
  durable `failed`-state design the plan's table actually uses.
- *F-4 (process): model label.* The issue is labelled `model:opus-5.5`
  (the intended paired reviewer), but this run was performed under
  Qwen3.8-27B (MTPLX-Optimized-Speed). The findings above are mechanical
  (line-by-line table comparison, proven guard, measured crash matrix), so
  they are model-independent; the label is recorded here so the sign-off is
  not mistaken for an Opus one. Not a code finding and not a blocker.

## Duplicate check

`bd list --all` (checked at `origin/main` `f803732`): the only move
issues are b8p.22 (this PR), its review b8p.23 (this one), the
review-fix `organize_music-225` (closed, merged into PR #59 as `e845703`),
and b8p.24 (Move recovery, open — it owns the recovery-table crash tests
and the S/V/D decisions, so F-1/F-2/F-3 are filed as a separate small
issue, not folded into it). No existing open issue covers the cleanup
logging, the error-code vocabulary, or the dead exception classes, so one
new P3 issue is filed and no duplicate exists.

# Review: Move recovery (b8p.24)

Paired review of `organize_music-b8p.24` (crash recovery for the move
operation, plan §6.2 recovery table: `src/organize_music/ops/recover_move.py`
plus `tests/ops/test_recover_move.py`; PR #68, feature commit `7add4c0`).
The review target is the code as it is on `origin/main` `7add4c0` after
b8p.24 landed. Catalogue id P1-14-R.

Reviewer: Hermes run `20261125_123144_8dd290` (model
Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed). The issue carries the label
`model:opus-5.5`; this run used Qwen3.8-27B, so the verdict is offered for
the human reviewer to confirm under the intended model, not as a binding
Opus sign-off (flagged below as finding F-3, not a code finding).

## Verdict

**Approve.** No safety findings, nothing blocks the next phase (b8p.26
"Recovery dispatcher", b8p.36 "End-of-phase review"). The module matches
the plan §6.2 recovery table row by row (`WEB_UI_PLAN.md:335-345`); the
one doubled-entry danger state is the only place the module would remove
anything, and there it removes *nothing* — the exFAT two-entries-one-cluster
chain case stops for a human (`recover_move.py:56-60`, plan `:344`);
preconditions gate every durable change (size/mtime before the commit,
`row_version` + `status` re-guarded as compare-and-set inside the commit
transaction); the no-unsafe-calls guard passes, is proven effective by a
plant in this run, and a hand search of the PR #68 diff found zero raw
replace/delete calls in `src/`. One minor, non-blocking finding is filed
as a new P3 issue (F-1: the shipped crash matrix never crashes the
recovery pass itself — probed safe in this run, not yet a committed test);
one documented deviation is recorded (F-2) and needs no action.

## What the module does (and how it maps to plan §6.2)

`recover_move(op, ctx)` (`recover_move.py:27-42`) re-reads the op row
(`:35`), rejects non-move ops with an explicit `ValueError` (`:36-37`),
re-runs `planned` ops through `run_move` (`:38-39` — a planned move never
touched the disk, plan §6.2 main table `:329`; `run_move` rechecks the
precondition, `move.py:59-90`), returns terminal ops unchanged (`:40-41`,
which makes a second recovery call a no-op), and otherwise dispatches to
`_recover_active` (`:45-67`). `_recover_active` samples the disk picture
S/V/D with `fs.entry_exists` on the *exact* names (`:52-54`, plan §6.1
`:307-308`; `primitives.py:176-187` compares the exact names from
`os.listdir` and is False when the parent directory is missing) and then
applies the §6.2 recovery table:

| Plan §6.2 recovery row (`WEB_UI_PLAN.md:338-345`) | Code | Match |
|---|---|---|
| S ✓ V ✗ D ✗ — rename never happened → `rmdir_if_empty` the `created_dirs` in reverse; op `failed` (`INTERRUPTED`) | `_src_only` `recover_move.py:70-79`: `_clean_created_dirs` (`:110-122`) walks `created_dirs` reversed (`:116`), each `rmdir_if_empty` removes only an empty directory (`primitives.py:127-139`) and any non-removal or `OSError` stops the walk best-effort (`:117-122`); then `failed` + `INTERRUPTED`/`"rename did not persist"` (`:73-76`) | ✓ — one documented deviation for the *unreachable* picture from `staged`/`applied`: **F-2** |
| S ✗ V ✓ D ✗ — case-only half done → `rename_noreplace(via, dst)`, then the applied path | `_via_only` `:82-87`: `fs.rename_noreplace(via, dst)` (`:84`), `fsync_dir(dst.parent)` (`:85`), transition to `applied` (`:86`), then `_dst_only` (the applied path) | ✓ |
| S ✗ V ✗ D ✓ (size and mtime match) — rename done → verify, then commit | `_dst_only` `:90-107`: `os.stat(dst)` (`:92`), size **and** `mtime_ns` compared to the op's expectations (`:93`), transition to `applied` when not already (`:95-96`), then the `committed` transition with `files_write.update_path` as `extra` in the same transaction (`:104-107`) | ✓ |
| S ✗ V ✗ D ✓ (mismatch) — something else is at dst → `needs_attention` | `_dst_only` `:93-94`: mismatch → `needs_attention`/`"dst mismatch: something else is at the destination"`, before any transition or disk change | ✓ |
| S ✓ (any V) D ✓ — both names exist → `needs_attention`, **never remove either** (exFAT power cut leaves two entries sharing one cluster chain; the UI tells the owner to run `fsck.exfat`) | `_recover_active` `:56-60`: any two of the three flags → `needs_attention`/`"two entries exist (...); run fsck on the volume"`; no removal call on this path at all | ✓ (the fsck wording is generic; the volume-specific `fsck.exfat` banner is the §6.5/phase-7 server banner, `:427-430`) |
| S ✗ V ✗ D ✗ — file not found → `needs_attention` | `_recover_active` `:67` → `needs_attention`/`"file not found at src, via or dst"` | ✓ |

The doubled-entry check runs *before* any single-name branch
(`:56-60` precedes `:61-67`), so the "never remove either" rule cannot be
bypassed by a branch order. The only removal-capable call in the module
(`rmdir_if_empty`, `:118`) is reached only from the S-only branch — where
at most one of the three names exists by construction — and it acts on
directories only. The via name is the op's own `.om-<op_id>.tmp`
(`plan_move_params`, `move.py:24-35`), so `_via_only`'s rename moves the op's
own file, never a foreign one; the no-replace primitive
(`primitives.py:61-101`, with the `lexists` pre-refusal `:72-73`) still
refuses a dst that appears in the race window.

Durable failure codes written via `transition(error=...)`: `INTERRUPTED`
(`:75`) and `NEEDS_ATTENTION` (`:60, :79, :94, :127`) — explicit
`(code, detail)` pairs, consistent with the forward path's vocabulary
(b8p.23, F-2 there noted `CROSS_DEVICE` as the one undocumented code).

## Checklist (every item answered, with evidence)

- **Plan sections read; the code compared line by line.** Plan §6.1
  (`WEB_UI_PLAN.md:300-320`), §6.2 main table (`:327-333`) and recovery
  table (`:335-345`), §6.5 durability (`:414-430`) were read; the mapping
  table above covers every §6.2 recovery row against
  `recover_move.py` with line references. No drift beyond the two
  documented items below (F-2 deviation, noted; the module docstring's
  own quotation of the "never remove either" rationale at `:7-12` matches
  the plan verbatim). The move edges in `states.py:19-23` (unchanged by
  PR #68) already reviewed in b8p.17 make the `failed`/`needs_attention`
  targets used here legal.

- **Every state transition has a crash-matrix test (FaultyFs before/after
  each fs call) followed by recovery and assert_consistent, where the
  module performs disk changes.**
  `test_crash_matrix_extended_with_recovery`
  (`tests/ops/test_recover_move.py:510-542`) measures the fs-call count of
  a clean `run_move` with `count_calls` (`:505-507`), then, for *every* fs
  call, `before` and `after`, runs the move under `FaultyFs`
  (`tests/support/faulty_fs.py:85-118`), catches the `SimulatedCrash`
  (a `BaseException`, `faulty_fs.py:76-83`), recovers on the *same* DB with
  `RealFs` (`:531`), asserts `assert_consistent`
  (`support/invariants.py`, `:532`), the op state in `{committed, failed}`
  (`:534`), and that a second recover call is a no-op (`:535-542`),
  parameterised over both move shapes (`:510-512`). Measured in this run:
  **7 fs calls → 14 crash points** (`a/one.mp3 → a/new/one.mp3`) and
  **8 → 16** (case-only) — 30 crash points, all passing (31 tests in the
  file, **31 passed**). The module's own disk-change paths
  (`_via_only`'s rename+fsync `:84-85`; `_clean_created_dirs`' rmdir walk
  `:116-118`; `_dst_only` makes no disk change) are each exercised to a
  terminal, consistent state by the row tests plus this matrix. **Gap
  (finding F-1):** the matrix crashes `run_move`, never `recover_move`
  itself — a torn *recovery* (crash between the via→dst rename and the
  `applied` transition, or mid-rmdir-walk) has no committed test. Probed
  in this review with a 20-point FaultyFs sweep of the recovery pass
  (6 points on the row-1 rmdir walk, 10 on the row-2 `_via_only`, 4 on the
  row-3 probes): **all settle** — a second clean recovery drives the op to
  a terminal state, `assert_consistent` holds, and the settled state is
  idempotent. Not a safety finding (safety rests on the primitives and the
  verify-before-commit order, both proven); the missing committed test is
  filed as P3.

- **No code path can replace or delete a library file.**
  `pytest -q tests/test_no_unsafe_calls.py` → **3 passed** (exit 0). The
  guard is proven effective in this run: an `os.remove` call planted at
  `src/organize_music/_probe_tmp.py` made
  `test_no_unsafe_filesystem_calls_outside_fsops` **fail**, and after
  removing the plant the file passed again (3 passed, together with
  `test_file_length.py` → 4 passed). A hand search of the PR #68 diff
  (`gh pr diff 68`; exactly `src/organize_music/ops/recover_move.py` +127,
  `tests/ops/test_recover_move.py` +542; 28 228 chars) for
  `os.rename|os.replace|os.remove|os.unlink|shutil.move|shutil.rmtree|Path.rename|.rename(|.replace(|.unlink(|os.rmdir`
  over added lines returned **7 matches, all in the test file** (fixture
  setup: six `(env.root / "a/one.mp3").unlink()` calls that build the
  row disk pictures, and one `via.rename(src)` at `test_recover_move.py:431`
  that builds the S-only picture for the F-2 test) and **zero in src/**.
  Every disk-mutating call in the added `src/` code goes through the fsops
  primitives: `ctx.fs.entry_exists` (×3, `:52-54`, read-only `os.listdir`),
  `ctx.fs.rename_noreplace` (`:84`), `ctx.fs.fsync_dir` (`:85`),
  `ctx.fs.rmdir_if_empty` (`:118` — `os.rmdir` removes a *directory* and
  only when empty, `primitives.py:127-139`, so it cannot delete a file),
  plus read-only `os.stat` (`:92`). No raw `os.remove`/`os.unlink`/
  `shutil` anywhere in the added code.

- **Preconditions (path, size, mtime_ns, row_version) are checked before
  the first disk change.** The only disk-changing recovery path is
  `_via_only` (`:82-87`); before its `rename_noreplace` the module does
  only read-only `entry_exists` sampling (`:52-54`). The rename cannot
  replace (no-replace primitive + `lexists` pre-refusal) and cannot alter
  bytes; the destination's *content* is then verified (size **and**
  `mtime_ns`, `:92-94`) **before** the first DB change, and the commit
  re-guards `row_version` and `status = 'present'` as a compare-and-set
  inside the same transaction (`files_write.py:58-67`, `StaleRow`/
  `PathTaken` on mismatch; `oplog_repo.py:151-162` rolls the transaction
  back and does not mirror on failure). That matches the plan's row-2
  ordering exactly ("`rename_noreplace(via, dst)`, **then the applied
  path**", `WEB_UI_PLAN.md:341`) — the plan itself prescribes verifying
  after the via→dst rename, so no unverified state is ever persisted.
  Row 3 (`_dst_only`) makes no disk change at all: verify, then commit.
  Row 1's only changes are empty-directory removals of the op's own
  `created_dirs` (cannot touch a file). `planned` re-runs through
  `run_move`, whose `_planned` re-stat + row re-read before the first disk
  change was verified in b8p.23 (`move.py:59-90`, unchanged by PR #68).

- **Errors are explicit and use the documented codes; no bare `except`, no
  `except: pass`, nothing swallowed.** `recover_move.py` has exactly one
  `except` clause — `except OSError: removed = False` in
  `_clean_created_dirs` (`:119-120`) — explicit, not bare; its result is
  used (the best-effort walk stops); it cannot catch `SimulatedCrash`
  (a `BaseException`, `faulty_fs.py:76-83`). Durable codes: `INTERRUPTED`
  (`:75`) and `NEEDS_ATTENTION` (`:60, :79, :94, :127`), all explicit
  `(code, detail)` pairs. Every other error — `DestinationExists`,
  `UnsupportedPlatform`, `OSError`, `StaleRow`/`PathTaken`,
  `IllegalTransition`, and the `ValueError` for non-move ops (`:37`) —
  propagates uncaught to the caller with the op left in its last durable
  state (the `oplog_repo.py:160-162` handler rolls back and re-raises;
  nothing is swallowed).

- **Tests were written first and cover the failure cases listed in
  b8p.24 (collision, precondition failed, crash at each step).** b8p.24's
  PROGRESS note records the TDD order: "tests written RED (collection:
  module missing), recover_move.py implemented (137 lines), gate green
  (446 passed, 1 skipped); extended crash matrix re-run through recovery
  passes at every point" (the file is 127 lines at the feature commit
  `7add4c0` — trimmed between the note and the commit; both under the
  200-line limit). Coverage of the listed cases in
  `tests/ops/test_recover_move.py` (31 tests, **31 passed** this run):
  one per recovery row — row 1 ×3 (`:275-309`, incl. non-empty folder kept
  `:287-294` and the staged-state stop `:297-309`), row 2 ×2 states
  (`:312-324`), row 3 ×3 states (`:327-335`) plus the no-disk-change
  commit replay (`:338-346`), row 4 ×2 (size mismatch `:349-356`, same-size
  different-mtime `:359-367`), row 5 ×4 (doubled entry `:370-378`,
  case-alias `:381-390`, src+via `:393-400`, via+dst `:403-412`), row 6
  (`:415-419`); *collision* in the recovery sense is covered by those
  stranger-at-dst/doubled-entry tests (the forward-path collision tests
  were verified in b8p.23); *precondition failed* by `:437-446` (planned
  op whose source changed → `PRECONDITION_FAILED`, row marked `changed`);
  *crash at each step* by the extended matrix `:510-542` (30 points);
  planned re-run (`:427-434`), terminal no-op ×4 (`:449-459`), non-move
  rejection (`:462-477`), and a second-call no-op per row (`:485-497`).

- **Files are <= 200 lines, typed signatures, no dead code.**
  `wc -l`: `ops/recover_move.py` **127**;
  `tests/ops/test_recover_move.py` 542 (test files are outside the guard's
  scope — `tests/test_file_length.py` scans `src/organize_music` only and
  passes; precedent recorded in the b8p.23 note). Every signature in
  `recover_move.py` is typed (`recover_move(op: Operation, ctx: OpContext)
  -> Operation` `:27`, `_recover_active` `:45`, `_src_only` `:70`,
  `_via_only` `:82`, `_dst_only` `:90`, `_clean_created_dirs(...) -> None`
  `:110`, `_needs_attention(...) -> Operation` `:125`, the nested
  `update(conn: object) -> None` `:104` — the same pattern as
  `move.py:137`). No dead code: all seven functions are reachable
  (`recover_move` → `_recover_active` → the four row handlers /
  `_needs_attention`; `_clean_created_dirs` from `_src_only`).

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.25` (from `origin/main` `7add4c0`), run under the
project venv:

```
ruff check .          -> All checks passed!
ruff format --check . -> 117 files already formatted
pytest -q            -> 449 passed, 1 skipped, 4 warnings in 5.78s
```

The 1 skip is the case-sensitive-filesystem skip in
`tests/fsops/test_primitives.py` (case-only rename primitives; it runs on
the Pi's exFAT and on APFS) — pre-existing and unrelated. The 4 warnings
are yoyo's deprecated default `datetime` adapter — pre-existing and
unrelated. `tests/ops/test_recover_move.py` (31),
`tests/test_no_unsafe_calls.py` (3, incl. the plant proof above) and
`tests/test_file_length.py` (1) are all green.

## Findings

None blocking. No safety findings: no path in the PR can replace or delete
a library file (guard + plant + diff search above), the doubled-entry state
removes nothing, preconditions gate every durable change, and the crash
matrix plus the torn-recovery probe below prove consistency at every
injected crash. One new P3 issue is filed (F-1); F-2 is recorded as an
accepted deviation and F-3 is a process note. None blocks b8p.26 or
b8p.36.

- *F-1 (minor, coverage): the crash matrix never crashes the recovery pass
  itself.* `test_crash_matrix_extended_with_recovery`
  (`test_recover_move.py:510-542`) injects every crash into `run_move` and
  then recovers on a clean `RealFs`; a crash *inside* `recover_move`
  (between the via→dst rename and the `applied` transition in
  `_via_only`, or mid-walk in `_clean_created_dirs`) is not covered by any
  committed test. This review probed all 20 such points
  (row 1: 3 fs calls → 6 points; row 2: 5 → 10; row 3: 2 → 4) with
  `FaultyFs` followed by a second clean recovery: **all settle** — the op
  reaches a terminal state, `assert_consistent` holds, and the settled
  state is idempotent (probe: `/tmp/torn_recovery_probe.py`, run in this
  session; the shipped harness makes it a one-liner to commit). Filed as a
  new P3 issue with `discovered-from:organize_music-b8p.25`; it does not
  block the next phase.
- *F-2 (documented deviation, no action): row 1 from a later state stops
  for a human instead of failing.* The plan's recovery table is keyed on
  S/V/D alone and row 1 prescribes `failed (INTERRUPTED)`
  (`WEB_UI_PLAN.md:340`); the code (`recover_move.py:73-79`) only fails
  when `states.ALLOWED` has a `failed` edge, i.e. from `intent`, and
  returns `needs_attention` when the S-only picture is observed from
  `staged` or `applied` (which have no `failed` edge, `states.py:22-23`
  — mirroring the plan's own §6.2 main table, `:330-332`). That picture is
  unreachable barring external interference: a rename's persistence is
  monotonic, and the exFAT power-cut that leaves the old entry also leaves
  the new one (two entries, caught at `:56-60`); if a human *does* restore
  the source by hand, stopping for a human is the safe answer. The
  behaviour is explained in the code comment (`:77-78`) and locked in by
  `test_recover_move.py:297-309`. Recorded here so the deviation from the
  table's literal text is visible; no change requested.
- *F-3 (process): model label.* The issue is labelled `model:opus-5.5`
  (the intended paired reviewer), but this run was performed under
  Qwen3.8-27B (MTPLX-Optimized-Speed). The findings above are mechanical
  (line-by-line table comparison, proven guard, measured crash matrices,
  probed torn recovery), so they are model-independent; the label is
  recorded here so the sign-off is not mistaken for an Opus one. Not a
  code finding and not a blocker.

## Duplicate check

`bd list --all` (195 issues, checked at `origin/main` `7add4c0`): no open
issue covers the torn-recovery matrix gap. `organize_music-fcj` is the
move *operation* (b8p.22) findings bundle (cleanup logging, `CROSS_DEVICE`
vocabulary, dead exception classes) — different scope; b8p.26/b8p.27 own
the recovery *dispatcher*, not the matrix; `organize_music-3yw`'s missing
crash-matrix note is about the migration runner; the `mau.*` retag
recovery tickets are a later phase for the other op kind. One new P3 issue
is therefore filed for F-1 and no duplicate exists.

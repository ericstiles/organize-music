# Review: Recovery dispatcher (b8p.26)

Paired review of `organize_music-b8p.26` (the startup recovery dispatcher,
plan §6.4 Startup: `src/organize_music/ops/recover.py` plus
`tests/ops/test_recover.py`; PR #70, feature commit `208ba65`, merged
2026-11-25). The review target is the code as it is on `origin/main`
`b999713` after b8p.26 landed. Catalogue id P1-15-R.

Reviewer: Hermes run `20261125_155854_0f780f` (model
Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed). The issue carries the label
`model:opus-5.5`; this run used Qwen3.8-27B, so the verdict is offered for
the human reviewer to confirm under the intended model, not as a binding
Opus sign-off (flagged below as finding F-2, not a code finding). Same
situation as the b8p.25 review (its finding F-3).

## Verdict

**Approve.** No safety findings, nothing blocks the next phase
(b8p.30 "Rename one file from the UI", b8p.36 "End-of-phase review").
The module matches b8p.26's contract exactly — `RecoveryReport(committed,
failed, needs_attention)` and `recover_all(ctx)` dispatching by kind with
`move` → `recover_move` and every other kind → terminal
`needs_attention` — and it performs no filesystem calls of its own, so the
no-replace/no-delete invariant and the precondition ordering rest entirely
on the already-reviewed `recover_move` (b8p.25) and `run_move` (b8p.23);
its one durable write is a single atomic oplog transaction, whose
rollback and convergence were probed in this run (finding F-1 covers the
missing committed test).

## What the module does (and how it maps to the plan and the contract)

`recover_all(ctx)` (`recover.py:35-62`) walks
`ctx.oplog.active_ops()` (`:49`) — every op in an `ACTIVE` state, ordered
by `op_id` (`oplog_repo.py:166-172`; `ACTIVE = {intent, staged, parked,
applied}`, `states.py:16`) — and drives each to a terminal state via
`_recover_one` (`:50, :65-69`): a `move` goes through `recover_move`
(`:67-68`), any other kind goes to `_no_recovery` (`:69, :72-84`), which
takes the op to terminal `needs_attention` with the explicit error pair
`("NEEDS_ATTENTION", "no recovery registered for kind …")` (`:80-84`).
Outcomes count into the frozen `RecoveryReport` (`:21-32`); an outcome
that is none of `committed`/`failed`/`needs_attention` raises
`RuntimeError` naming the op and the state (`:57-61`) instead of being
silently dropped.

Line-by-line against the contract quoted in b8p.26 ("What to do") and
plan §6.4 Startup (`WEB_UI_PLAN.md:409-410`):

| Contract element | Code | Match |
|---|---|---|
| `@dataclass(frozen=True) RecoveryReport` with `committed: int`, `failed: int`, `needs_attention: tuple[int, ...]` | `recover.py:21-32` — frozen, exactly those three fields and types | ✓ |
| `recover_all(ctx: OpContext) -> RecoveryReport` | `recover.py:35` — exact signature | ✓ |
| "for op in oplog.active_ops(): dispatch by kind ('move' → recover_move)" | `recover.py:49-50, :65-69` | ✓ |
| "unknown kind → transition needs_attention" | `recover.py:72-84` — terminal `needs_attention` via `ctx.oplog.transition`, documented as standing in for the phase-5 `retag` recovery | ✓ |
| Plan §6.4 Startup: "run `recover` over every operation in `intent`, `staged`, `parked`, or `applied` **before** the worker accepts jobs" | `active_ops()` returns exactly those four states (`states.py:16`, `oplog_repo.py:166-172`); the "before the worker accepts jobs" sequencing plus the lock/migration/mount preamble is server/CLI wiring owned by the later P1-19/serve issues, outside b8p.26's scope (its "Files" section is `ops/recover.py` + tests only) | ✓ (scope boundary noted) |
| Plan §6.4: "Jobs left `running` become `interrupted`" | Job (not operation) state; the job runner is a later phase. No operation in an in-flight state escapes this dispatcher: `active_ops()` covers all four `ACTIVE` states and no other state can exist for an op that touched the disk (the `planned` state never did, `run_move` rechecks its precondition before its first disk change — verified in b8p.23) | ✓ (out of scope, recorded) |

No drift found. The `needs_attention` targets are legal from every
`ACTIVE` state for both known kinds (`states.py:20-28`: every active row
has a `needs_attention` edge), so `_no_recovery` cannot hit
`IllegalTransition` under the current schema; if the transition table
ever loses an edge, `IllegalTransition` raises and writes nothing
(`oplog_repo.py:144-147`) — the op stays active and the next startup
retries, never a silent drop.

## Checklist (every item answered, with evidence)

- **Plan sections read; the code compared line by line.** Plan §6.4
  (Startup bullet at `WEB_UI_PLAN.md:409-410`) and the §6.2 state model
  were read; the mapping table above covers the full b8p.26 contract
  against `recover.py` with line references. The only boundary items
  (job `interrupted`, lock/migration/mount preamble) are explicitly later
  phases in the catalogue (P1-19 `serve`/`recover` CLI, the web server)
  and outside b8p.26's "Files" scope — recorded, not a drift.

- **Every state transition has a crash-matrix test (FaultyFs before/after
  each fs call) followed by recovery and assert_consistent, where the
  module performs disk changes.** `recover.py` performs **no filesystem
  calls at all**: its body is a loop over `active_ops()` (DB read,
  `oplog_repo.py:166-172`), dispatch to `recover_move`, and — for unknown
  kinds — one `oplog.transition` (one atomic SQLite transaction:
  `UPDATE` + `commit`, rollback + no mirror on failure,
  `oplog_repo.py:127-164`). There is no multi-step fs sequence inside
  this module to matrix; the disk-changing code it dispatches to is
  already matrixed: `recover_move`'s 30-point crash matrix and 20-point
  torn-recovery probe were verified in the b8p.25 review (its findings
  F-1/F-2; the committed gap is tracked as `organize_music-6yg`). This
  run probed the pass itself (probe script
  `/tmp/dispatcher_crash_probe.py`, run in this session): a full
  `recover_all` over the three-picture mixed library makes
  **10 fs calls → 20 mid-pass crash points** under `FaultyFs`
  (before/after each call), and **all 20 settle** — after the crash a
  clean pass drives every op to a terminal state, `assert_consistent`
  holds, and a second clean pass is a byte- and record-level no-op; the
  two dispatcher-level durable writes were also crashed at their
  `commit` (a `sqlite3.Connection` subclass with an overridable
  `commit`): the `needs_attention` transition's commit rolled back with
  the op row untouched and the mirror not written, and the committed
  transition's commit (op row + `files` row as `extra`, one transaction)
  rolled back both rows — both then converge on a clean pass. **Gap
  (finding F-1):** none of this is a committed test; filed as P3
  `organize_music-h1e` (discovered-from b8p.27).

- **No code path can replace or delete a library file.**
  `pytest -q tests/test_no_unsafe_calls.py` → **3 passed** (part of the
  473). The guard is proven effective in this run: an `os.remove` call
  planted at `src/organize_music/_probe_b8p27.py` made
  `test_no_unsafe_filesystem_calls_outside_fsops` **fail** (1 failed,
  2 passed), and after deleting the plant the file passed again (together
  with `tests/test_file_length.py` → 4 passed; the tree is clean).
  A hand search of the PR #70 diff (`git show 208ba65`; exactly
  `src/organize_music/ops/recover.py` +84 and
  `tests/ops/test_recover.py` +299) over added lines, using the guard's
  own patterns, returned **3 matches, all in the test file** — the
  fixture-setup `(lib.root / …).unlink()` calls that build the disk
  pictures (`test_recover.py:193, :200, :290`) — and **zero in src/**.
  `recover.py` contains no filesystem call of any kind, safe or unsafe;
  its only disk-adjacent action is the DB transition.

- **Preconditions (path, size, mtime_ns, row_version) are checked before
  the first disk change.** The dispatcher performs no disk change, so the
  ordering is inherited from what it dispatches to, all verified in the
  paired reviews: `recover_move` samples the disk read-only
  (`entry_exists` ×3, `recover_move.py:52-54`) before its one disk change
  (the no-replace `via→dst` rename, `:84-85`), verifies the destination's
  size **and** `mtime_ns` before its first DB write (`:92-94`), and the
  commit re-guards `row_version` (+ `status`) as a compare-and-set inside
  the same transaction (`files_write.update_path`, `files_write.py:58-67`;
  rolled back and un-mirrored on failure, `oplog_repo.py:160-163`) —
  details and line evidence in the b8p.25 review doc; `planned` re-runs
  re-stat before any change (`move.py:59-90`, b8p.23). The dispatcher's
  own one durable write (`_no_recovery`'s `needs_attention` transition)
  has no fs effect at all, and this run's commit-crash probes show the
  transaction rolls back atomically when it dies.

- **Errors are explicit and use the documented codes; no bare `except`,
  no `except: pass`, nothing swallowed.** `recover.py` has **zero**
  `except` clauses (grep for `except` over the file: no match). Errors it
  raises: `RuntimeError` for an unexpected terminal outcome (`:57-61` —
  the message names the op id and the offending state; under the current
  schema it is unreachable — no `ACTIVE` state has a `skipped` edge,
  `states.py:20-28` — and it is locked in by
  `test_unexpected_terminal_outcome_fails_loudly`,
  `test_recover.py:282-299`, which monkeypatches `recover_move` to return
  `state="skipped"`). `IllegalTransition` and everything `recover_move`
  raises propagate uncaught to the caller with the op left in its last
  durable state. The only durable code this module writes is
  `NEEDS_ATTENTION` (`:83`), an explicit `(code, detail)` pair, consistent
  with the `recover_move` vocabulary (`INTERRUPTED`, `NEEDS_ATTENTION`).

- **Tests were written first and cover the failure cases listed in
  b8p.26.** b8p.26's PROGRESS note records the TDD order: "tests written
  (tests/ops/test_recover.py, 8 tests), RED confirmed
  (ModuleNotFoundError: organize_music.ops.recover)". The committed file
  holds 8 test cases in 5 functions:
  `test_three_active_moves_mixed_disk_states` (`:213-243`) — one op per
  §6.2 disk picture (A: V-only case-only rename, B: D-only, C: S-only with
  a created folder; built by `build_mixed`, `:180-210`), asserting the
  exact report `(committed=2, failed=1, needs_attention=())`, per-op
  terminal states, the `INTERRUPTED`/"rename did not persist" pair,
  `assert_consistent`, and a no-op second pass;
  `test_no_ops_report_is_zero` (`:246-249`);
  `test_planned_ops_are_untouched_and_report_is_zero` (`:252-260`);
  `test_unknown_kind_goes_to_needs_attention` (`:263-279`, parametrised
  over all four active states); `test_unexpected_terminal_outcome_fails_
  loudly` (`:282-299`). All three cases b8p.26 listed to write first
  (three active moves in different disk states; no active ops → zeros;
  unknown kind → needs_attention) are present, **8/8 pass** in this run.

- **Files are <= 200 lines, typed signatures, no dead code.**
  `wc -l`: `ops/recover.py` **84**; `tests/ops/test_recover.py` 299 —
  outside the guard's scope: `tests/test_file_length.py` scans
  `src/organize_music` only (`:7-15`) and passes; every >200-line file in
  the repo is a test file (10 files; the pending `organize_music-c6s`
  will codify the rule as "200-line **src** files"). Every signature in
  `recover.py` is typed: `recover_all(ctx: OpContext) -> RecoveryReport`
  (`:35`), `_recover_one(ctx: OpContext, op: Operation) -> Operation`
  (`:65`), `_no_recovery(ctx: OpContext, op: Operation) -> Operation`
  (`:72`), the frozen dataclass fields (`:30-32`). No dead code: all
  three functions are reachable from `recover_all`, and all three report
  fields are read by the tests.

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.27` (from `origin/main` `b999713`), run under the
project venv (Python 3.13.5, ruff 0.17.5):

```
ruff check .          -> All checks passed!
ruff format --check . -> 121 files already formatted
pytest -q            -> 473 passed, 1 skipped, 4 warnings in 5.35s
```

The 1 skip is the case-sensitive-filesystem skip in
`tests/fsops/test_primitives.py:80` (case-only rename primitives; runs on
exFAT/APFS) — pre-existing and unrelated. The 4 warnings are yoyo's
deprecated default `datetime` adapter — pre-existing and unrelated.
`tests/ops/test_recover.py` (8), `tests/test_no_unsafe_calls.py` (3, incl.
the plant proof above) and `tests/test_file_length.py` (1) are all green.

## Findings

None blocking. No safety findings: the module makes no filesystem calls
(guard + plant + diff search above), its one durable write is an atomic
transaction proven to roll back cleanly (commit-crash probes), and the
disk-changing code it dispatches to was cleared in b8p.25. Two
non-blocking findings:

- *F-1 (minor, coverage): the committed tests never crash the pass
  itself.* `tests/ops/test_recover.py` has no `FaultyFs` and no
  mid-pass/commit-crash test. This review probed all of it
  (`/tmp/dispatcher_crash_probe.py`, run in this session): 10 fs calls →
  20 mid-pass `FaultyFs` crash points (before/after each), all settle
  (ops terminal, `assert_consistent`, idempotent second pass); plus the
  two transition-commit crash points (rollback, mirror untouched,
  convergence). Not a safety finding — SQLite makes the transition
  atomic and the disk work's own matrix lives in `recover_move`
  (b8p.25, and its committed-test gap is `organize_music-6yg`) — but the
  committed dispatcher-level test is filed as P3
  `organize_music-h1e` (discovered-from organize_music-b8p.27); it does
  not block the next phase.
- *F-2 (process): model label.* The issue is labelled `model:opus-5.5`
  (the intended paired reviewer), but this run was performed under
  Qwen3.8-27B (MTPLX-Optimized-Speed), exactly as the b8p.25 review was
  (its F-3). The findings above are mechanical (contract mapping, proven
  guard, measured probes), so they are model-independent; the label is
  recorded here so the sign-off is not mistaken for an Opus one. Not a
  code finding and not a blocker.

## Duplicate check

`bd list --all` (196 issues, checked at `origin/main` `b999713`): the
only adjacent open issue is `organize_music-6yg` (P3, "crash
recover_move itself at every fs call") — that is the *recovery target's*
torn matrix, a different module and a different crash surface from the
*dispatcher's* pass/commit gap; `organize_music-fcj` is the move
operation's findings bundle; no open issue covers the
`recover_all`-level torn-pass or transition-commit tests. One new P3
issue is therefore filed (F-1) and no duplicate exists.

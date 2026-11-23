# Review: Operation log repository with allowed transitions (b8p.16)

Paired review of `organize_music-b8p.16` (the crash-safe operation log over the
`operations` table: `ops/states.py`, `ops/oplog_repo.py`, `ops/_rows.py`, merged
on PR #48, feature commit `2e687c9`, merge commit `8a033bd`). The review target
is the code as it is on `origin/main` `f29cee2` after b8p.16 landed. Catalogue id
P1-10-R.

Reviewer: Hermes run `20261122_200338_f1ad8f` (**model qwen3.8-27**). The issue
carries the label `model:opus-5.5`; this run used qwen3.8-27, so the verdict is
offered for the human reviewer to confirm under the intended model, not as a
binding Opus sign-off (flagged below as a process note, not a code finding).

## Verdict

**Approve.** No safety findings, nothing blocks the next phase, and no new issue
is filed. The operation-log module is correct and safe: the transition table is
exactly the plan's §6.2/§6.3 tables (the happy path plus the crash-recovery
terminal edges), every refuse path writes nothing, the `extra` (the future
files-table write) and the op-state update commit together and roll back together,
the mirror is appended only after a successful commit, nothing in the module can
replace or delete a library file (the no-unsafe-calls guard is proven by a plant),
every public signature is typed, every file is under 200 lines, and the quality
gate is green (`370 passed, 1 skipped`).

The one checklist item that cannot be *exercised* by this module — the FaultyFs
crash matrix — is not a defect: `OplogRepo` performs no filesystem calls
itself, so the per-file crash matrix is the job of the move/retag operation that
b8p.16's `extra` callback will later inject (P1-13/P1-14, not built yet). This is
the same scoping the b8p.6 / b8p.12 / b8p.21 reviews used for the
support/primitive layers this module sits on.

## What the module does (and why the checklist items scope the way they do)

`OplogRepo` is a *database* layer, not a *filesystem* layer. Its only writes are
to `library.db` (the `operations` and `batches` tables). The disk work of a move
— `mkdir_one`, `rename_noreplace`, the `files` row update — is performed by the
caller-supplied `extra(conn)` callback *inside* the transition's transaction, so
the op-state change and the file effect are one atomic unit
(`oplog_repo.py:142-164`). The JSONL mirror is a *separate* write, appended
**after** the commit (`oplog_repo.py:163`), so a crash between them leaves the
log and the files in their last committed state and the mirror simply re-appends
the record on recovery.

The crash-safety guarantee therefore rests on two things, both verified below:
(1) each transition is one durable transaction — `commit()` after the op update,
with `rollback()` on any exception — and the writer connection that runs it is
opened with `PRAGMA synchronous=FULL` + WAL (`db/connection.py:22-25`), the
durable-commit guarantee PLAN §6.1 names; (2) a refuse (illegal transition) writes
nothing. The per-file FaultyFs crash matrix (`tests/support/faulty_fs.py`,
`tests/support/invariants.assert_consistent`) is used only by the support harness
today — `grep -rln FaultyFs` finds `tests/support/` and nothing under `src/` or
`tests/ops/` — because there is no operation *driver* to drive it yet (b8p.22,
"Move operation execution", is not built). The module's own crash resilience is
instead proven by the purpose-built atomicity tests that simulate exactly the
crash of interest: a crash mid-transition (the `extra` raises) → rollback,
nothing committed, mirror untouched
(`tests/ops/test_oplog_repo.py:284-308`).

## Checklist (every item ticked, with evidence)

- **Plan §6.2/§6.3 read; the transition table compared line by line.**
  `ops/states.py:19-29` is the §6.2 move table and §6.3 retag table, verbatim,
  *plus* the terminal edges the §6.2/§6.3 **recovery** tables add
  (`→ failed`, `→ skipped` from `planned`; `→ needs_attention` from every active
  state; `→ committed` from `applied`):

  | kind | from | allowed to | source |
  |------|------|-----------|--------|
  | move | planned | intent, failed, skipped | §6.2 row + §6.2 recovery (`INTERRUPTED`→failed) |
  | move | intent | applied, staged, failed, needs_attention | §6.2 intent/applied/staged + recovery |
  | move | staged | applied, needs_attention | §6.2 `staged→applied` + recovery |
  | move | applied | committed, needs_attention | §6.2 `applied→committed` + recovery |
  | retag | planned | intent, failed, skipped | §6.3 row + recovery |
  | retag | intent | staged, failed, needs_attention | §6.3 intent→staged + recovery |
  | retag | staged | parked, failed, needs_attention | §6.3 `staged→parked` + recovery |
  | retag | parked | applied, failed, needs_attention | §6.3 `parked→applied` + recovery |
  | retag | applied | committed, needs_attention | §6.3 `applied→committed` + recovery |

  `states.py:12` `TERMINAL = {committed, failed, skipped, needs_attention}` and
  `states.py:16` `ACTIVE = {intent, staged, parked, applied}` match the
  `operations.state` CHECK domain in `0001_initial.sql:88`
  (`planned,intent,staged,parked,applied,committed,failed,skipped,needs_attention`
  = planned ∪ ACTIVE ∪ TERMINAL) and the `operations_one_active_per_file` partial
  index predicate (`0001_initial.sql:96-97`, `WHERE state IN
  ('intent','staged','parked','applied')`), which `ACTIVE` is exactly. `is_allowed`
  (`states.py:32-34`) is a single membership test over `ALLOWED` with a
  fail-closed default (`frozenset()` for an unknown `(kind, from)`), so an
  unlisted pair is refused. No drift from the plan.

- **Crash-matrix test (FaultyFs before/after each fs call) + recovery +
  `assert_consistent`, where the module performs disk changes.** N/A for this
  module, for the reason in the section above: `OplogRepo` makes **no**
  filesystem calls (verified by hand — see the next item), so there is nothing for
  the FaultyFs matrix to inject a crash into. The module's own crash point — a
  crash *mid-transition* — is covered by
  `test_extra_that_raises_leaves_op_and_files_unchanged`
  (`tests/ops/test_oplog_repo.py:284-308`): the `extra` writes a `files` row then
  raises, the transition's `rollback()` (`oplog_repo.py:160-161`) undoes both the
  file write and the op-state change, and the mirror is not appended
  (`len(records) == 1`, only the earlier `intent` drive). Same N/A scoping as
  b8p.6/b8p.12/b8p.21; no defect, and the gap (a FaultyFs-driven crash matrix for
  the move/retag *driver*) is b8p.22's, already on the queue.

- **No code path can replace or delete a library file.** Verified three ways.
  1. *Hand search of the b8p.16 diff and the whole `ops/` tree.*
     `git diff 2e687c9~1 2e687c9 -- src/organize_music/ops/` and a grep of
     `src/organize_music/ops/*.py` for `rename|replace|unlink|remove|rmtree|shutil`
     return **nothing**. The module's only I/O is `sqlite3`
     (`self._conn.execute`/`commit`/`rollback`, `oplog_repo.py:72,96,122,154,159,161`),
     `json.dumps`/`json.loads` (serialising the `params` mapping, not a file), and
     the `mirror`/`clock` callables the caller injects. There is no raw
     filesystem call to speak of.
  2. *The guard test is effective, not merely present.* Planting
     `os.remove("x")` in `src/organize_music/_probe_tmp.py` made
     `tests/test_no_unsafe_calls.py::test_no_unsafe_filesystem_calls_outside_fsops`
     **fail** with `_probe_tmp.py:4: os.remove()  ->  os.remove("x")`; after
     deleting the probe it passed. The guard is real.
  3. *The guard's own scope.* `tests/test_no_unsafe_calls.py:30` scans every
     `*.py` under `src/organize_music` except `fsops/`; `ops/` is in scope and
     clean. No code path in the operation log can replace or delete a library
     file. (The sanctioned `os.replace` for report paths lives in `fsops/`, which
     the guard excludes and records at `test_no_unsafe_calls.py:64-68`.)

- **Preconditions (path, size, mtime_ns, row_version) checked before the first
  disk change.** N/A as an *oplog* responsibility, verified as *carried*.
  `add_op` persists the four preconditions into the row — `expect_path`,
  `expect_size`, `expect_mtime_ns`, `expect_row_version`
  (`oplog_repo.py:97-115`, bound from `expect[0..3]`), and `get`/`_to_op`
  project them back out (`_rows.py:18-22`, `oplog_repo.py:175-191`). The
  *compare-and-set* that uses them before the first disk change is the
  `extra` the caller injects: `files_write.update_path` guards
  `WHERE file_id = ? AND row_version = ? AND status = 'present'`
  (`db/files_write.py:56-67`) and raises `StaleRow`/`PathTaken` on a mismatch,
  leaving the row untouched. That check runs *inside* the transition's
  transaction, before the op-state update (`oplog_repo.py:152-158`), so a stale
  precondition fails the whole transition and writes nothing. The oplog's job is
  to carry the preconditions durably; the check itself is b8p.14's, and it is
  green.

- **Errors are explicit and use the documented codes; no bare `except`, no
  `except: pass`, nothing swallowed.** The module raises exactly one of its own
  types: `IllegalTransition` (`oplog_repo.py:25-29,144-147`), a clear,
  documented refuse. A failed transition carries the caller's error pair:
  `transition(..., error=("E_NOFILE", "the source vanished"))` stores
  `error_code`/`error_detail` and mirrors them (`oplog_repo.py:149-157`,
  `_rows.py:39-40`), proven by `test_failed_transition_records_error`
  (`tests/ops/test_oplog_repo.py:242-252`). The only `except` in the module is
  `except BaseException: rollback(); raise` (`oplog_repo.py:160-162`) — it
  *re-raises* after rolling back, it swallows nothing, and using `BaseException`
  (not `Exception`) is the PLAN §6.1 property that lets a
  `SimulatedCrash`/`KeyboardInterrupt` propagate instead of being caught. A grep
  of `src/organize_music/ops/` for `except\s*:|except.*pass` returns nothing.
  Nothing is swallowed.

- **Tests written first, covering the failure cases listed in b8p.16.** b8p.16's
  "Tests to write first" list is all present in `tests/ops/test_oplog_repo.py`
  (384 lines, 45 passed):
  - *every allowed transition succeeds* → `test_every_allowed_transition_succeeds`
    (`:194-204`), parameterised over the 24 `ALLOWED_CASES` (`:165-191`);
  - *a table of disallowed ones raises and leaves the row unchanged* →
    `test_disallowed_transition_raises_and_leaves_row_unchanged`
    (`:223-239`), parameterised over the 11 `DISALLOWED_CASES` (`:208-220`) that
    include `move planned→committed`, `move committed→intent`,
    `retag planned→parked`, a self-transition, and the terminal states;
  - *a transition whose `extra` raises leaves both the op and the files
    unchanged* → `test_extra_that_raises_leaves_op_and_files_unchanged`
    (`:284-308`);
  - *mirror called once per success, not on failure* →
    `test_mirror_called_once_per_success_and_not_on_failure`
    (`:316-329`) and `test_mirror_record_carries_the_transition` (`:332-345`);
  - *the unique index prevents two active ops on one file* →
    `test_two_active_ops_on_one_file_are_prevented` (`:353-368`), which asserts
    the second `→ intent` raises `sqlite3.IntegrityError` and that the second op
    stayed `planned`.
  The TDD record (red phase then green) is in PR #48; the b8p.16 note confirms
  "tests written … full quality gate green". The crash-at-each-step coverage for
  the *driver* is b8p.22's (see the crash-matrix item above).

- **Files <= 200 lines, typed signatures, no dead code.** `states.py` is 34
  lines, `oplog_repo.py` 191, `_rows.py` 45, `__init__.py` 18 — all under 200,
  and `tests/test_file_length.py` (which scans `src/organize_music` only) is
  green. Every public signature is typed:
  `is_allowed(kind: str, from_state: str, to_state: str) -> bool`
  (`states.py:32`); `OplogRepo.__init__(conn: sqlite3.Connection,
  mirror: Callable[[Mapping[str, object]], None], clock: Callable[[], str])
  -> None` (`oplog_repo.py:59-64`);
  `create_batch(self, kind: str, description: str, request_json: str) -> int`
  (`:69`); `add_op(self, batch_id: int, file_id: int, unit_seq: int,
  step_seq: int, kind: str, expect: tuple[str, int, int, int],
  params: Mapping[str, object]) -> int` (`:80-89`);
  `get(self, op_id: int) -> Operation` (`:120`);
  `transition(self, op_id: int, to: str, params: Mapping[str, object] | None =
  None, error: tuple[str, str] | None = None,
  extra: Callable[[sqlite3.Connection], None] | None = None) -> Operation`
  (`:127-134`); `active_ops(self) -> list[Operation]` (`:166`);
  `record(op: Operation, to: str, params: Mapping[str, object],
  error_code: str | None, now: str) -> dict[str, object]`
  (`_rows.py:25-31`). No dead code: `ruff check .` (incl. F401/F811/F841) is
  clean, and every `__all__` entry in `__init__.py` is exercised — `ACTIVE`
  drives `active_ops` (`oplog_repo.py:168-170`) and the test asserts it
  (`:384`), `TERMINAL` is the public re-export, and `is_allowed`/`ALLOWED` are
  used by both the module and the test's BFS driver
  (`test_oplog_repo.py:102,196,227`). `tests/ops/test_oplog_repo.py` is 384
  lines, but the 200-line limit scans `src/` only, so it is out of scope by
  design (same scoping as b8p.6/b8p.21).

## b8p.16 acceptance criteria, re-checked

- *All listed tests pass.* `pytest -q tests/ops/` → **45 passed**.
- *Atomicity (the core safety claim).* `extra` and the op-state update commit
  together and roll back together (`oplog_repo.py:151-162`), the mirror is
  appended only after the commit (`:163`), and an illegal transition writes
  nothing (the check at `:144-147` runs before any write and raises). Confirmed by
  `test_extra_runs_inside_the_transaction_and_is_seen_after_commit`
  (`:260-281`) and `test_extra_that_raises_leaves_op_and_files_unchanged`
  (`:284-308`).
- *`operations_one_active_per_file`* partial index enforces "at most one active
  op per file" (`0001_initial.sql:96-97`), and `ACTIVE` is exactly its predicate
  (`states.py:16`, asserted at `test_oplog_repo.py:384`). Confirmed by
  `test_two_active_ops_on_one_file_are_prevented` (`:353-368`).
- *Out of scope respected.* No disk operations were added by b8p.16 (the diff is
  purely `ops/` + `tests/ops/`), and the mirror is the injectable callable the
  issue specified ("inject a `list.append` in tests") — `make_repo`
  (`test_oplog_repo.py:61-63`) — so the JSONL mirror implementation (P1-11) is
  correctly left un-built.

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.17` (from `origin/main` `f29cee2`), run under the project
venv (Python 3.13.5, which satisfies `requires-python >=3.12`; the sandbox's
system `python` is 3.11 and lacks the project deps, so the venv is used, as in the
b8p.6/b8p.12/b8p.21 reviews — the gate is mechanical, not a runtime pin):

```
ruff check .          -> All checks passed!
ruff format --check . -> 97 files already formatted
pytest -q            -> 370 passed, 1 skipped, 2 warnings
```

The 1 skip is `tests/fsops/test_primitives.py::test_rename_noreplace_case_only_*`
— skipped because the sandbox's filesystem is case-sensitive (it runs on the Pi's
exFAT and on APFS); it is unrelated to this change. The 2 warnings are yoyo's
`DeprecationWarning` (default datetime adapter), unrelated to this change.
`tests/ops/test_oplog_repo.py` (45), `tests/test_no_unsafe_calls.py` (3, incl.
the plant proof above) and `tests/test_file_length.py` (1) are all green.

## Findings

None blocking. No safety findings, nothing blocks the next phase (b8p.18 /
b8p.22 / b8p.36), and no new issue is filed. Two observations, neither a code or
safety defect:

- *Observation (crash-matrix scoping, not a defect).* As in b8p.6/b8p.12/b8p.21,
  the per-file FaultyFs crash matrix does not yet apply to this module: it is the
  *operation-log* layer, which performs no filesystem calls, and the in-flight /
  at-rest invariants live in the *operation driver* (b8p.22, the move/retag
  execution, not built). The module's own crash point — a crash *mid-transition*
  — is proven by the atomicity tests that simulate it
  (`test_extra_that_raises_leaves_op_and_files_unchanged`,
  `tests/ops/test_oplog_repo.py:284-308`), which is the correct and complete
  treatment for a database layer whose only crash window is its own transaction.
  The FaultyFs-driven matrix is b8p.22's, already on the queue.
- *Observation (model label, not a defect).* The issue is labelled
  `model:opus-5.5` (the intended paired reviewer), but this run was performed
  under **qwen3.8-27** and is offered for the human reviewer to confirm under the
  intended model. The findings above are mechanical (a line-by-line table
  comparison and a proven guard), so they are model-independent, but the label is
  recorded here so the sign-off is not mistaken for an Opus one. Not a code
  finding and not a blocker.

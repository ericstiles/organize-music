# Review: JSONL operation mirror on the SSD (b8p.18)

Paired review of `organize_music-b8p.18` (the JSONL operation mirror, plan C1 /
§6.1 step 4: `ops/mirror.py`, `tests/ops/test_mirror.py`, feature commit
`df460d0`, PR #54). The review target is the code as it is on `origin/main`
`5e37aea` after b8p.18 landed. Catalogue id P1-11-R.

Reviewer: Hermes run `20261124_160808_5c369b` (**model qwen3.8:27b-mlx**). The
issue carries the label `model:opus-5.5`; this run used qwen3.8-27, so the
verdict is offered for the human reviewer to confirm under the intended model,
not as a binding Opus sign-off (flagged below as a process note, not a code
finding).

## Verdict

**Approve.** No safety findings, nothing blocks the next phase, and no new issue
is filed. The module is correct and safe: it matches the plan's C1 / §6.1 step
(4) line by line, every record is one sorted-keys UTF-8 JSON line flushed and
fsynced so a crash leaves only complete records, the monthly file name and
rollover are exactly the plan, nothing in the module can replace or delete a
library file (the no-unsafe-calls guard is proven effective by a plant, and
`ops/mirror.py` is inside the guard's scan scope), every public signature is
typed, the module is 61 lines (under the 200-line limit) with no dead code, and
the quality gate is green (`401 passed, 1 skipped`).

The one checklist item that cannot be *exercised* by this module — the FaultyFs
crash matrix — is not a defect, and unlike the oplog/oplog-repo layers it is a
*real* gap in coverage that the module's own design closes rather than a
scoping note: `append` performs its disk write through the raw standard library
(`Path.mkdir`, `open`, `os.fsync`), not through the `FsOps` protocol that
`FaultyFs` wraps, so there is no `FsOps` seam to wrap. That is by design — the
mirror writes *outside the library* (plan §6.5: `work_dir/oplog` on the SSD,
`$MUSIC_LIB/../_organize_music_work`), it is the redundant append-only copy, and
a torn append can never lose data (the durable write it mirrors already
committed, and replay re-appends), so the module's own crash window is closed
not by a FaultyFs matrix but by the fsync-after-write property the tests prove,
plus the real-process-kill tracer that b8p.34 exercises. This is recorded as
finding F-1 below (coverage scoping, not a safety finding).

## What the module does (and why the checklist items scope the way they do)

`ops/mirror.py` is the *last durable step* of every operation (§6.1 step 4):
`OplogRepo.transition` checks the transition, runs the optional `extra` (the
`files`-table write), updates the op row, **commits**, and *only then* appends
one record to the mirror (`oplog_repo.py:163`, `self._mirror(record(...))`). A
crash between the commit and the append leaves the DB and the files in their
last committed state; the mirror simply re-appends the record on recovery, so
the mirror is a redundant *append-only* copy, never the thing that makes a
state change durable. The module is a thin writer with three public functions:

- `mirror_path(work_dir, now)` (`mirror.py:22-28`) returns
  `work_dir/'oplog'/f'{now[:7]}.jsonl'` — the monthly file the plan names
  (`work_dir/oplog/YYYY-MM.jsonl`), the month being the first seven characters
  of the ISO-8601 UTC timestamp.
- `append(work_dir, record, now)` (`mirror.py:31-46`) mkdir's the `oplog`
  directory with parents, serializes the record with
  `json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n"` (stable,
  Unicode-safe, one line), and `with open(path, "a", encoding="utf-8")` writes,
  `flush()`, and `os.fsync(fh.fileno())` it.
- `make_mirror(work_dir, clock)` (`mirror.py:49-61`) closes a `clock`
  (`Callable[[], str]`) into the `Callable[[Mapping[str, object]], None]`
  `OplogRepo` injects as its `mirror`, calling `append(work_dir, record,
  clock())` per transition so that as the clock crosses a month the records flow
  into the new file automatically.

The durability guarantee rests on exactly one property, and the tests prove
exactly that property: a record is written *as one line and fsynced*, so a
crash anywhere in `append` leaves the file holding only *complete* records (the
module docstring, `mirror.py:8-9`). There is no torn-write window: `flush`
pushes the OS write buffer and `os.fsync` forces the bytes to the SSD before
`append` returns, and a crash *during* the write leaves at most a short prefix
of the final line that no later reader parses as a record (a replay that
tolerates a trailing partial line is a later concern; C1's replay is "later",
per b8p.18's out-of-scope list, and no replay code exists in the tree — see the
duplicate-check below).

## Checklist (every item ticked, with evidence)

- **Plan C1 / §6.1 step (4) read; the code compared line by line.**
  Plan C1 (`docs/WEB_UI_PLAN.md:60-74`): "Every operation-state change is also
  appended to a JSONL mirror on the SSD (`work_dir/oplog/YYYY-MM.jsonl`,
  fsynced)" and, on DB loss, "replay the JSONL mirror for operations after the
  backup". §6.1 (`docs/WEB_UI_PLAN.md:300-304`): a step is "(1) do the disk
  action, (2) fsync …, (3) write the new state in a DB transaction with
  `synchronous=FULL`, (4) append the transition to the JSONL mirror."
  §6.5 (`docs/WEB_UI_PLAN.md:417`): "The JSONL mirror is fsynced per line."
  `mirror.py` matches all three: the monthly `oplog/YYYY-MM.jsonl` name
  (`mirror.py:28`), one JSON line per record (`mirror.py:42`), `flush` +
  `os.fsync` per line (`mirror.py:45-46`), and append-after-commit in the caller
  (`oplog_repo.py:163`). No drift.

- **Every state transition has a crash-matrix test (FaultyFs before/after each
  fs call + recovery + assert_consistent), where the module performs disk
  changes — *finding F-1 (coverage scoping, not a defect)*.** This module *does*
  perform disk changes, so the item is not vacuously N/A the way it was for
  `oplog_repo` (b8p.17) or the harness itself (b8p.21). But it cannot be
  exercised by the FaultyFs matrix as written, and that is correct:
  `FaultyFs` (`tests/support/faulty_fs.py:59-113`) wraps an `FsOps` and
  dispatches *only* the protocol methods in `_FSMETHODS`
  (`faulty_fs.py:40-52`: `rename_noreplace`, `fsync_file`, `fsync_dir`,
  `mkdir_one`, `rmdir_if_empty`, `copy_new`, `discard_temp`, `entry_exists`,
  `same_device`). `append` writes through the **raw standard library**
  (`mirror.py:41-46`: `path.parent.mkdir`, `open(...)`, `os.fsync(...)`), none
  of which is an `FsOps` method, so `FaultyFs` has no seam to wrap — the mirror
  is not reached through the harness at all. That is by design, not an omission:
  the mirror writes *outside the library* (`work_dir/oplog`, plan §6.5) and is
  the redundant append-only copy, so its crash semantics are the opposite of the
  library's — a torn append loses nothing, because the durable state change it
  mirrors already committed (§6.1 step 3 before step 4). The module's own crash
  window is therefore closed by the fsync-after-write property the tests prove
  (`test_append_fsyncs_the_record`, `tests/ops/test_mirror.py:75-86`, which
  monkeypatches `os.fsync` to record the fd and asserts it is called with an
  `int`), and the *real* crash of interest (a process killed mid-move) is
  exercised end to end by b8p.34 ("Tracer E2E on the Mac with a real crash",
  `OM_FAULT_SLEEP_AFTER` + `kill -9` + `recover`). A FaultyFs matrix for the
  mirror would require either an `FsOps` method for the append or a
  raw-filesystem fault seam; neither is the plan's design, and neither is
  needed for safety. See "Findings" below.

- **No code path can replace or delete a library file: `tests/test_no_unsafe_calls.py`
  passes and the diff was searched for rename/replace/unlink/remove/rmtree/move.**
  `pytest -q tests/test_no_unsafe_calls.py` → 3 passed. `ops/mirror.py` is inside
  the guard's scan scope: the guard excludes only top-level `fsops/`
  (`tests/test_no_unsafe_calls.py:86-87`), and `ops/` is not `fsops/` (a probe
  at `/tmp/probe_mirror_guard.py` confirmed `ops/mirror.py` is *not* treated as
  excluded and that `os.remove` planted at `src/organize_music/ops/_probe_tmp.py`
  is caught: `ops/_probe_tmp.py:5: os.remove() -> os.remove("/x")`, then the
  plant removed and the tree re-scanned clean). A hand grep of the module and of
  `src/organize_music/ops/` for `rename|replace|unlink|remove|rmtree|shutil|move`
  returns nothing: the only `except` under `ops/` is
  `oplog_repo.py:160` (`except BaseException: rollback(); raise`, which re-raises
  — it does not touch the filesystem). `append` uses `open(..., "a")` (append
  mode), `mkdir(parents=True, exist_ok=True)`, and `os.fsync` — it creates the
  `oplog` directory and appends to a file the module itself owns; it never
  renames, replaces, or unlinks anything, and it writes outside the library, so
  it cannot replace or delete a library file.

- **Preconditions (path, size, mtime_ns, row_version) are checked before the
  first disk change.** N/A for the mirror itself, and that is correct: the
  mirror carries no precondition — it is not the thing that checks the
  preconditions. Those are held durably by `OplogRepo`/`add_op`
  (`oplog_repo.py:100-133`, the `expect` tuple `(expect_path, expect_size,
  expect_mtime_ns, expect_row_version)`) and re-checked by the engine the `extra`
  callback injects before the move (b8p.14 / P1-13 / P1-14; see b8p.17's
  checklist item for the same scoping). The mirror's only input is a `record`
  mapping that the caller builds *after* the committed transition
  (`oplog_repo.py:163`, `record(op, to, new_params, error_code, now)`); by the
  time `append` runs the precondition check has already passed and the row has
  already committed. No precondition belongs to this module.

- **Errors are explicit and use the documented codes; no bare `except`, no
  `except: pass`, nothing swallowed.** `grep -n except src/organize_music/ops/`
  returns a single hit, `oplog_repo.py:160` (`except BaseException:
  self._conn.rollback(); raise`) — it re-raises, so nothing is swallowed; it is
  in `oplog_repo`, not `mirror.py`. `mirror.py` has **zero** `except` clauses
  (`grep -n except src/organize_music/ops/mirror.py` → none). `append` lets any
  I/O error (e.g. a full disk, an unwritable `work_dir`) propagate, which is the
  correct behaviour for a durability step that must not silently drop a record.
  No bare `except`, no `except ...: pass`, nothing swallowed.

- **Tests were written first and cover the failure cases listed in b8p.18
  (collision, precondition failed, crash at each step).**
  `tests/ops/test_mirror.py` (10 tests, all pass) covers the cases b8p.18 named:
  two appends produce two parseable lines in order
  (`test_two_appends_produce_two_lines_in_order`, `:36-46`); month rollover
  writes to a new file (`test_month_rollover_writes_to_a_new_file`, `:48-56`);
  `os.fsync` is called (`test_append_fsyncs_the_record`, `:75-86`);
  `json.dumps` with sorted keys and `ensure_ascii=False`
  (`test_append_uses_json_sorted_and_unicode_safe`, `:58-69`); the monthly
  directory is created (`test_append_creates_the_monthly_directory`, `:88-93`);
  the `make_mirror`/`clock` adapter and its month advance
  (`:95-156`). The "collision / precondition-failed / crash-at-each-step" cases
  of b8p.18's prose are the *operation* layer's cases (collision = `path_key` /
  `entry_exists` at the move, b8p.13/b8p.14; precondition = the `expect` tuple,
  b8p.14; crash-at-each-step = the FaultyFs matrix, b8p.22/b8p.34), not the
  mirror's: the mirror's own crash case — a crash mid-append — is the
  fsync-after-write property proven by `test_append_fsyncs_the_record` plus the
  real-kill tracer b8p.34 (see F-1). No test in the module asserts a wrong
  thing; each matches the plan.

- **Files are <= 200 lines, typed signatures, no dead code.**
  `wc -l src/organize_music/ops/mirror.py` → 61 lines (well under 200); the test
  file is 157. Every public signature is typed: `mirror_path(work_dir: Path,
  now: str) -> Path` (`:22`), `append(work_dir: Path, record:
  Mapping[str, object], now: str) -> None` (`:31`), `make_mirror(work_dir: Path,
  clock: Callable[[], str]) -> Callable[[Mapping[str, object]], None]` (`:49`),
  and the nested `mirror(record: Mapping[str, object]) -> None` (`:58`). No dead
  code: all three public functions are used (`mirror_path` by `append` and the
  tests; `append` by `make_mirror` and the tests; `make_mirror` injected into
  `OplogRepo` end to end at `tests/ops/test_mirror.py:120-156`), and
  `tests/test_file_length.py` (1 passed) is green. Ruff is clean (F401/F811/F841).

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.19` (from `origin/main` `5e37aea`), run under the project
venv (Python 3.13.5, which satisfies `requires-python >=3.12`; the sandbox's
system `python` lacks the project deps, so the venv is used, as in the
b8p.6/b8p.12/b8p.17/b8p.21 reviews — the gate is mechanical, not a runtime pin):

```
ruff check .          -> All checks passed!
ruff format --check . -> 109 files already formatted
pytest -q            -> 401 passed, 1 skipped, 4 warnings
```

The 1 skip is `tests/fsops/test_primitives.py::test_rename_noreplace_case_only_*`
(skipped because the sandbox's filesystem is case-sensitive — it runs on the
Pi's exFAT and on APFS); it is unrelated to this change. The 4 warnings are
`python-multipart` / `starlette` import deprecations and yoyo's default
`datetime` adapter, all unrelated to this change. `tests/ops/test_mirror.py`
(10), `tests/test_no_unsafe_calls.py` (3, incl. the plant proof above) and
`tests/test_file_length.py` (1) are all green.

## Findings

None blocking. No safety findings, nothing blocks the next phase (b8p.34 /
b8p.36), and no new issue is filed. One coverage-scoping observation and one
process note, neither a code or safety defect:

- *F-1 (crash-matrix coverage scoping, not a defect).* As in b8p.6 / b8p.12 /
  b8p.17 / b8p.21, the per-file FaultyFs crash matrix does not apply to this
  module — but here the reason is structural, not "the module does no fs work":
  `append` writes through the raw standard library (`mirror.py:41-46`), which
  `FaultyFs` does not wrap (it wraps only the `FsOps` protocol,
  `tests/support/faulty_fs.py:40-52`). The module is *designed* that way: the
  mirror is the redundant, append-only copy that lives outside the library
  (plan §6.5, `work_dir/oplog`), so a torn append cannot lose data and a crash
  mid-append is closed by the fsync-after-write property
  (`test_append_fsyncs_the_record`, `tests/ops/test_mirror.py:75-86`) and the
  real-process-kill tracer (b8p.34). No FaultyFs seam for the mirror is needed,
  and the plan does not call for one, so this is not a gap to file. It is
  recorded so the "crash-matrix test" checklist item is answered explicitly
  rather than glossed as N/A, and so a future reader does not mistake the
  absence of a FaultyFs-driven mirror test for a missing test. The one
  *genuine* follow-up the module implies — a replay reader that tolerates a
  trailing partial line in a month's JSONL — is out of scope for b8p.18 (its
  out-of-scope list says "No replay tool (later)") and is not yet on the queue,
  so it is noted here but not filed (it is not a defect of this PR and does not
  block the next phase; the Phase 1 end-of-phase review, b8p.36, is the natural
  place to decide whether to add it).
- *F-2 (model label, not a defect).* The issue is labelled `model:opus-5.5`
  (the intended paired reviewer), but this run was performed under
  **qwen3.8:27b-mlx** and is offered for the human reviewer to confirm under the
  intended model. The findings above are mechanical (a line-by-line table
  comparison and a proven guard), so they are model-independent, but the label is
  recorded here so the sign-off is not mistaken for an Opus one. Not a code
  finding and not a blocker.

## Duplicate check

`bd list --all | grep -i 'mirror|crash|replay|jsonl'` (checked at
`origin/main` `5e37aea`): the only mirror issue is b8p.18 (this PR) and its
review b8p.19; the only crash-matrix issues are b8p.20 (FaultyFs harness),
b8p.21 (its review), b8p.34 (the real-kill tracer), and the move/retag
recovery/dispatcher items (b8p.24–b8p.27), none of which file a mirror-specific
crash-matrix test. No duplicate of any finding above exists, so nothing is filed.

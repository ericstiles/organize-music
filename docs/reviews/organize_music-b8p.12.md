# Review: fsops — FsOps protocol and the no-unsafe-calls test (organize_music-b8p.12)

Paired review of `organize_music-b8p.11` (PR #31, merge commit `1221e78`,
`feat(organize_music-b8p.11): add FsOps protocol and no-unsafe-calls test (P1-7)`),
which added `src/organize_music/fsops/protocol.py` and
`tests/test_no_unsafe_calls.py` and rewired `cli_commands.py`: the injectable
filesystem interface (PLAN §6.1, invariant I7 "Library files are never replaced
or deleted") and the source-grep guard that enforces it. Catalogue id P1-7-R.

Reviewer: Hermes run `20261121_161623_0db995` (**model qwen3.8-27**, not the
`model:opus-5.5` the issue is labelled for; see *Discrepancy* below).

## Verdict

**Approve.** No safety findings. Nothing blocks the next phase; no new issue
filed. The module is a thin, stateless delegator plus one sanctioned atomic
report write; every guarantee it is responsible for holds, and the guard test it
adds is proven to fail on a planted violation.

The review re-read PLAN §6.1 "Rules every step follows" and §6.10 invariant I7,
and compared them to the merged code line by line. I also hand-searched the
entire `src/organize_music` tree for every forbidden call, ran a throwaway
plant (a forbidden `os.remove` outside `fsops/`) to confirm the guard test
actually fails, and ran the project's quality gate on this branch.

## Checklist (every item ticked, with evidence)

- **Plan §6.1 / §6.10 read, code compared line by line.** `docs/WEB_UI_PLAN.md`
  §6.1 (line 309-314) fixes the invariant: "No call that can replace or delete a
  library file exists in the code … A test greps `src/` for `os.rename`,
  `os.replace`, `Path.rename`, `Path.replace`, `os.remove`, `os.unlink`,
  `Path.unlink`, `shutil.move`, `shutil.rmtree` outside `fsops/` and fails if it
  finds any." §6.10 (line 506) fixes I7: "Library files are never replaced or
  deleted | fsops primitives only (app) and the source-grep test."
  `fsops/protocol.py` matches the §6.1 intent: `FsOps` is the nine-primitive
  interface and `RealFs` is its stateless implementation, so the engine receives
  an injectable `FsOps` (PLAN §11) and crash tests can wrap it.

- **Crash-matrix test (FaultyFs before/after each fs call) + recovery +
  assert_consistent, where the module performs disk changes.** N/A for this
  module. `FaultyFs`/`assert_consistent` are `organize_music-b8p.20` (still
  OPEN), and the crash matrix targets the *operations* that perform the state
  transitions of §6.2/§6.3 (`ops/move.py`, `ops/retag.py` — P1-13/P1-14),
  where a `SimulatedCrash` is raised at each disk action. This module is the
  primitive-delegation layer those ops call; a stateless delegator has no
  multi-step state transition to matrix. `write_text_atomic` does a single
  atomic report write (`mkdir` + sibling temp + `os.replace`, all on a path
  outside the library), which is atomic by construction and is not a state
  transition of the engine, so it needs no crash matrix. Same N/A reasoning as
  the b8p.4, b8p.8 and b8p.10 reviews (primitive/pure modules).

- **No code path can replace or delete a library file.** Verified two ways.
  1. *The guard test.* `tests/test_no_unsafe_calls.py::test_no_unsafe_filesystem_calls_outside_fsops`
     greps every `*.py` under `src/organize_music` except `fsops/` and fails
     listing `file:line` per hit. I confirmed it is **effective**, not merely
     present: planting `os.remove(x)` in a new `src/organize_music/_probe_tmp.py`
     made it fail with
     `_probe_tmp.py:3: os.remove()  ->  os.remove(x)`; after removing the probe
     the file passes (`3 passed`). A guard that cannot fail would be worthless;
     this one fails on a real violation.
  2. *A hand search of the whole tree* (including `fsops/`) found exactly three
     raw matches, all accounted for:
     - `fsops/primitives.py:173` `candidate.unlink()` — the guarded `discard_temp`
       unlink, already reviewed in b8p.10 (`^op-\d+\..*$` name + `resolve()` to
       `work_dir/tmp`; refuses the symlink/`..` escape).
     - `fsops/protocol.py:104` `os.replace(tmp, path)` in `write_text_atomic` —
       the one sanctioned replacing write, in `fsops/` (excluded from the scan),
       recorded with a one-line reason in the test's header.
     - `markdown.py:10` `".replace("|", ...)` — a `str.replace` string op,
       allow-listed via the `_STR_RECEIVER_MARKERS` string-literal check.
     Crucially, `write_text_atomic`'s `os.replace` target is always a *report*
     path: both call sites (`run_meta`, `run_dupes`) call
     `_ensure_outside(root, report, "report")` (`cli_commands.py:39`,
     `cli_commands.py:81`) before writing, so the swap can never touch a library
     file. No code path outside `fsops/` can replace or delete a library file.

- **Preconditions (path, size, mtime_ns, row_version) checked before the first
  disk change.** N/A as an engine responsibility. Per §6.1/§6.2 the precondition
  re-stat/re-read belongs to the operations layer (P1-13/P1-14), not built yet;
  this module holds and checks no precondition. `write_text_atomic` takes no
  precondition argument and performs no pre-change guard, which is correct for a
  report writer. (The precondition *check itself* is the caller's job.)

- **Errors are explicit and use the documented codes; no bare except, no
  `except: pass`, nothing swallowed.** `protocol.py` has **zero** `except`
  clauses — it only delegates, and the crash-safe guarantees (errno →
  `DestinationExists`/`UnsupportedPlatform`, the guarded `discard_temp`
  `ValueError`) live in `primitives.py`, reviewed in b8p.10. A hand grep of all
  three changed files found no bare `except`, no `except: pass`, and no
  swallowed error. `RealFs`'s methods `return` the primitive's value
  (`rmdir_if_empty`, `entry_exists`, `same_device`) so the boolean results
  propagate; the `None`-returning delegators (`rename_noreplace`, `copy_new`,
  `discard_temp`, `mkdir_one`, `fsync_file`, `fsync_dir`) do not swallow —
  exceptions from the primitive propagate normally.

- **Tests written first, covering the failure cases in b8p.11.** PR #31 records
  TDD: **RED** — `test_no_unsafe_filesystem_calls_outside_fsops` failed on
  `cli_commands.py:33: tmp.replace(path)` (a raw `Path.replace`) and
  `test_real_fs_satisfies_fsops_protocol` failed with
  `ModuleNotFoundError: No module named 'organize_music.fsops.protocol'`;
  **GREEN** after implementing `protocol.py` and moving `_write_atomic` out.
  `tests/test_no_unsafe_calls.py` has 3 tests covering the cases that belong to
  *this* module: the guard (a forbidden call appears → fail, proven by the plant
  above); `RealFs` satisfies `FsOps` (`isinstance` with `@runtime_checkable`);
  and `RealFs` delegates every method to a real directory
  (`test_real_fs_delegates_to_the_primitives`). The "collision / precondition
  failed / crash at each step" cases in the checklist belong to the ops layer
  (P1-13/P1-14), not to a stateless delegator plus a guard, so they are out of
  scope here — same scoping as the b8p.9/b8p.10 reviews.

- **Files <= 200 lines, typed signatures, no dead code.**
  `fsops/protocol.py` is 104 lines; every one of the 9 protocol methods plus
  `write_text_atomic` has a typed signature (the 9 protocol methods at
  `protocol.py:35-52`; `RealFs` delegates at `protocol.py:58-87`;
  `write_text_atomic` at `protocol.py:90`). `tests/test_no_unsafe_calls.py` is
  163 lines; `cli_commands.py` net -6 lines (removed `_write_atomic`, added one
  import and two call-site rewires). No dead code: every `__all__` entry
  (`FsOps`, `RealFs`, `write_text_atomic`) is defined and exercised —
  `RealFs`/`FsOps` by `test_real_fs_satisfies_fsops_protocol` and
  `test_real_fs_delegates_to_the_primitives`, `write_text_atomic` by the two
  `cli_commands` call sites. The 9 protocol methods mirror the 9 `primitives`
  signatures exactly (names, parameters, returns):
  `rename_noreplace(src,dst)`, `fsync_file(path)`, `fsync_dir(path)`,
  `mkdir_one(path)`, `rmdir_if_empty(path)`, `copy_new(src,dst)`,
  `discard_temp(work_dir,path)`, `entry_exists(parent,name)`,
  `same_device(*paths)` — verified against `primitives.py:61,104,113,122,127,142,162,176,190`.

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.12` (from `origin/main` `f6ed3fb`), run under the
project venv (Python 3.13.5, which satisfies `requires-python >=3.12`; the
sandbox's system `python` is 3.11 and lacks the project deps, so the venv is
used, as the issue's "Done when" is a mechanical gate not a runtime pin):

```
ruff check .          -> All checks passed!
ruff format --check . -> 75 files already formatted
pytest -q            -> 290 passed, 1 skipped, 2 warnings
```

The 1 skip is `test_rename_noreplace_case_only_raises_on_case_insensitive`,
skipped because the sandbox's filesystem is case-sensitive (the test runs on the
Pi's exFAT and on APFS). The 2 warnings are a yoyo-migrations
`DeprecationWarning` (default datetime adapter) from `test_migrations.py`,
unrelated to this change.

## Findings

None blocking. No safety findings, nothing blocks the next phase, no new issue
filed. The only observation is operational, not a code defect (see *Discrepancy*
below).

## Discrepancy (operational, noted not blocking)

The issue and its `model:opus-5.5` label, and PLAN §11 ("Fable 5.2 reviews
fsops"), expect this review by a stronger model than the one that actually
performed it (this run is **qwen3.8-27**). The review is mechanical — a
line-by-line code/plan comparison, an effective-guard proof by plant, and a
quality gate — so the model choice does not change the technical verdict. The
finding is recorded here and in the PR body so the owner can decide whether to
have the fsops reviews re-run by the labelled model; it is not a code or safety
finding and does not block the phase.

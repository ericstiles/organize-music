# Review: Crash-test support — FaultyFs and assert_consistent (organize_music-b8p.21)

Paired review of `organize_music-b8p.20` (PR #37, merge commit `9f0812f`,
`feat(organize_music-b8p.20): add crash-test support (FaultyFs, count_calls,
assert_consistent)`, plus the `docs(organize_music-iga)` follow-up commit
`06e2953`), which added `tests/support/__init__.py`,
`tests/support/faulty_fs.py`, `tests/support/invariants.py` and
`tests/support/test_support.py`: the crash-matrix harness of PLAN §11
(PLAN §11 "Crash matrix", invariants I3/I5 "at most one in-flight operation
per file" / "no operation stays non-terminal at rest", and PLAN §6.1
"SimulatedCrash subclasses BaseException"). Catalogue id P1-12-R.

Reviewer: Hermes run `20261121_212808_e4d5f2` (**model qwen3.8-27**, not the
`model:opus-5.5` the issue is labelled for; see *Discrepancy* below).

## Verdict

**Approve.** No safety findings. Nothing blocks the next phase; no new issue
filed. The module is a test-only harness (it is imported by no production
code), and every guarantee the harness is responsible for holding is correct:
`SimulatedCrash` escapes `except Exception`, `FaultyFs` crashes *before* vs
*after* the right call, `assert_consistent` checks the three §11 invariants,
and the one raw `.unlink()` in the diff is a test that proves the failure case,
not a violation of invariant I7.

The review re-read PLAN §6.1 (the "SimulatedCrash subclasses BaseException"
rule), §6.4 (startup recovery over `intent`/`staged`/`parked`/`applied`) and
§11 (the crash-matrix spec and the three `assert_consistent` checks), and
compared them to the merged code line by line. I hand-searched the PR #37 diff
and the whole `src/organize_music` tree for every forbidden call, ran a
throwaway plant to confirm the no-unsafe-calls guard still fails on a real
violation, and ran the project's quality gate on this branch.

## Checklist (every item ticked, with evidence)

- **Plan §6.1 / §11 read, code compared line by line.** PLAN §6.1 (line 331)
  fixes the rule: "`SimulatedCrash` (tests only) subclasses `BaseException`, so
  no `except Exception` in the engine can swallow it." PLAN §11 (lines 643-650)
  fixes the harness: "`tests/support/faulty_fs.py` wraps `FsOps` and raises
  `SimulatedCrash` before or after the n-th call … For every n, run the op,
  crash, run recovery on a fresh engine with the real fs, then assert —
  `assert_consistent` holds: the multiset of file-content hashes under the root,
  the purge folder, and `tmp/` covers the originals; every `present` row matches
  disk; no active operations remain." The code matches this intent:
  `faulty_fs.py:76` `class SimulatedCrash(BaseException)`, `FaultyFs`
  (`faulty_fs.py:85-118`) crashes before/after the `crash_at`-th call, and
  `assert_consistent` (`invariants.py:62-116`) performs exactly the three §11
  checks. No drift.

- **Every state transition has a crash-matrix test (FaultyFs before/after each
  fs call) + recovery + assert_consistent, where the module performs disk
  changes.** N/A for this module — it is the *harness* the crash matrix is built
  on, not an op that performs a state transition. The §11 matrix itself
  (per-op crash-at-every-call → recovery → `assert_consistent`) targets the
  operations layer that is not built yet (P1-13 `ops/move.py`, P1-14
  `ops/retag.py`). What *this* module supplies, and is proven by its own tests,
  is the primitive the matrix drives: `FaultyFs` crashes at the right call
  (`test_faulty_fs_crashes_before_the_nth_call_and_inner_is_untouched`,
  `test_faulty_fs_crashes_after_the_nth_call_and_inner_is_reached`,
  `test_support.py:70-98`), and `crash_points` (`faulty_fs.py:9-46`, the §11
  "before and after" sweep) is documented as a fixture example in the module
  docstring, guarded by `test_module_docstring_documents_the_crash_points_fixture`
  (`test_support.py:21-30`). Same N/A scoping as the b8p.4/b8p.8/b8p.10/b8p.12
  reviews (support/primitive modules).

- **No code path can replace or delete a library file.** Verified three ways.
  1. *The harness is test-only.* `tests/support/__init__.py:7-8` states the
     package "must never be imported by the production engine," and nothing
     under `src/organize_music` imports `tests/` — the harness can change no
     library file by construction.
  2. *The guard test.* `tests/test_no_unsafe_calls.py::test_no_unsafe_filesystem_calls_outside_fsops`
     still greps every `*.py` under `src/organize_music` except `fsops/` and
     fails listing `file:line` per hit. I confirmed it is **effective**, not
     merely present: planting `os.remove("x")` in a new
     `src/organize_music/_probe_tmp.py` made it fail with
     `_probe_tmp.py:4: os.remove()  ->  os.remove("x")`; after deleting the probe
     it passes (`1 passed`).
  3. *A hand search of the PR #37 diff and the whole tree.* The only forbidden
     call in the diff is `test_support.py:208`
     `(root / "a/b/c.mp3").unlink()` — inside
     `test_assert_consistent_fails_when_a_file_is_removed`, the deliberate
     "remove a file, expect `assert_consistent` to fail" case. It is a test on a
     throwaway `tmp_path` library, not a library-file deletion, and it is outside
     the guard's `src/` scan scope. A hand search of all of
     `src/organize_music` found exactly two raw matches, both sanctioned and both
     in `fsops/` (excluded from the scan): `fsops/primitives.py:173`
     `candidate.unlink()` — the guarded `discard_temp` unlink (b8p.10) — and
     `fsops/protocol.py:104` `os.replace(tmp, path)` in `write_text_atomic`, the
     one sanctioned *report*-path write (b8p.12). No code path can replace or
     delete a library file.

- **Preconditions (path, size, mtime_ns, row_version) checked before the first
  disk change.** N/A as an engine responsibility. The precondition re-stat/
  re-read belongs to the operations layer (P1-13/P1-14, not built). This module
  holds and checks no precondition; `FaultyFs`/`assert_consistent` take no
  precondition argument and perform no pre-change guard, which is correct for a
  test harness. (The precondition *data* the checks read — `expect_path`,
  `expect_size`, `expect_mtime_ns`, `expect_row_version` — is the operations
  schema, `0001_initial.sql:86-88`, reviewed in b8p.5.)

- **Errors are explicit and use the documented codes; no bare except, no
  `except: pass`, nothing swallowed.** `faulty_fs.py` has **zero** `except`
  clauses — it raises `SimulatedCrash` (`faulty_fs.py:111,115`) and forwards
  everything else to `inner` unchanged, so engine exceptions propagate.
  `invariants.py` has **zero** `except` clauses; every violation raises a
  specific `AssertionError` with a reason (`invariants.py:80-82,94,97-99,101-104,112-116`).
  A hand grep of the three new files found no bare `except` and no `except:
  pass`. The only `except` clauses in the diff are in `test_support.py`
  (`except SimulatedCrash`, `except Exception`, `except AssertionError`) —
  every one is a test assertion that *re-raises* `AssertionError` on the
  unexpected path (`test_support.py:77,92,119-120,124,211,232,264`), so nothing
  is swallowed. `SimulatedCrash` escaping `except Exception` is itself proven by
  `test_simulated_crash_is_not_caught_by_except_exception`
  (`test_support.py:110-127`).

- **Tests written first, covering the failure cases in b8p.20.** PR #37 records
  TDD: **RED** — the four `assert_consistent` tests and the two `FaultyFs`
  timing tests fail on the absent harness; **GREEN** after implementing
  `faulty_fs.py`/`invariants.py`. `tests/support/test_support.py` (269 lines,
  9 tests) covers the failure cases the ticket lists: `FaultyFs` raises on the
  n-th call *before* (inner untouched) and *after* (inner reached),
  `SimulatedCrash` is not caught by `except Exception`, `count_calls` runs once
  and returns the total, `content_hashes` hashes as documented, and
  `assert_consistent` passes on a clean tree and **fails** when a file is
  removed, when a present row's size is wrong, and when an operation is left
  in-flight (the three §11 invariants, `test_support.py:192-269`). The
  "collision / precondition-failed / crash-at-each-step" cases belong to the ops
  layer (P1-13/P1-14), not to the harness that those tests will call, so they
  are out of scope here — same scoping as the b8p.9/b8p.10/b8p.12 reviews.

- **Files <= 200 lines, typed signatures, no dead code.**
  `tests/support/__init__.py` is 9 lines; `faulty_fs.py` is 129 lines;
  `invariants.py` is 116 lines. Every public signature is typed:
  `SimulatedCrash` (`faulty_fs.py:76`), `FaultyFs.__init__`
  (`faulty_fs.py:96`), `count_calls(run: Callable[[FaultyFs], object), inner:
  FsOps) -> int` (`faulty_fs.py:121`), `_file_hash(path: Path) -> str`
  (`invariants.py:34`), `content_hashes(*dirs: Path) -> Counter[str]`
  (`invariants.py:42`), `assert_consistent(root, conn, extra_dirs:
  Sequence[Path], original: Counter[str]) -> None` (`invariants.py:62-67`).
  `test_support.py` is 269 lines — over 200, but **not a violation**: the 200-line
  limit is enforced by `tests/test_file_length.py`, which scans `SRC`
  (`src/organize_music`) only (`test_file_length.py:4-20`); test files are out of
  that scope by design, and longer test files are already merged
  (`tests/db/test_migrations.py` 618, `tests/test_cli.py` 397,
  `tests/fsops/test_primitives.py` 359). No dead code: `ruff check
  tests/support/` (incl. F401/F811/F841) is clean, and every `__all__` entry
  (`SimulatedCrash`, `FaultyFs`, `count_calls`, `content_hashes`,
  `assert_consistent`) is defined and exercised by a test.

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.21` (from `origin/main` `2d976be`), run under the
project venv (Python 3.13.5, which satisfies `requires-python >=3.12`; the
sandbox's system `python` is 3.11 and lacks the project deps, so the venv is
used, as the issue's "Done when" is a mechanical gate not a runtime pin):

```
ruff check .          -> All checks passed!
ruff format --check . -> 80 files already formatted
pytest -q            -> 304 passed, 1 skipped, 2 warnings
```

The 1 skip is `test_rename_noreplace_case_only_raises_on_case_insensitive`,
skipped because the sandbox's filesystem is case-sensitive (it runs on the Pi's
exFAT and on APFS). The 2 warnings are a yoyo-migrations `DeprecationWarning`
(default datetime adapter) from `test_migrations.py`, unrelated to this change.

## Findings

None blocking. No safety findings, nothing blocks the next phase, no new issue
filed. Two observations, neither a code or safety defect:

- *Observation (scoping, not a defect).* `_ACTIVE_STATES`
  (`invariants.py:31`) is `{intent, staged, parked, applied}`, mirroring the
  `operations_one_active_per_file` partial index
  (`0001_initial.sql:96-97`) and the §6.4 startup-recovery states exactly — it
  does **not** include `planned`. This is correct: a `planned` operation is
  written to the batch and run in the same job (`§6.4` "writes the batch and its
  `planned` operations in one transaction and runs them"), so it is never an
  at-rest in-flight state a crash leaves behind; `planned` is also not in the
  partial index, so the harness and the schema agree. The "no active operation at
  rest" check is therefore faithful to I3/I5.
- *Observation (spec nuance, not a defect).* `count_calls`'s type is
  `Callable[[FaultyFs], object]` (`faulty_fs.py:121`), a one-argument callable
  matching the docstring's usage example (`crash_points` calls
  `count_calls(lambda fs: run_move(op, ctx(fs)), inner)`); the ticket's prose
  wrote `Callable[[FsOps], object]`. The signature is the right one for the
  documented call and `run(wrapper)` passes the `FaultyFs` wrapper, so the
  difference is a ticket wording nit, not a code issue.

## Discrepancy (operational, noted not blocking)

The issue and its `model:opus-5.5` label expect this review by a stronger model
than the one that actually performed it (this run is **qwen3.8-27**). The review
is mechanical — a line-by-line code/plan comparison, an effective-guard proof by
plant, and a quality gate — so the model choice does not change the technical
verdict. The finding is recorded here and in the PR body so the owner can decide
whether to have this review re-run by the labelled model; it is not a code or
safety finding and does not block the phase. (Same operational note as the
b8p.12 review.)

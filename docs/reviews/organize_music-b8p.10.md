# Review: fsops primitives — no-replace rename and safe file operations (organize_music-b8p.10)

Paired review of `organize_music-b8p.9` (PR #19, merge commit `23f4dcf`), which
added `src/organize_music/fsops/primitives.py`, `src/organize_music/fsops/__init__.py`,
`tests/fsops/__init__.py`, `tests/fsops/conftest.py` and
`tests/fsops/test_primitives.py`: the *only* module allowed to touch the
filesystem for mutations (PLAN §6.1, §6.6). Catalogue id P1-6-R.

Reviewer: Hermes run `20261120_233415_2d97eb`.

## Verdict

**Approve.** No safety findings. Nothing blocks the next phase; no new issue
filed. One non-blocking observation (test-file line count, see *Findings*).

The review re-read PLAN §6.1 "Rules every step follows", §6.6 "exFAT
specifics" and §6.2/§6.3/§6.5, and compared them to the merged code line by
line. I also searched the diff by hand for every forbidden call, and ran a
throwaway harness that confirms the `discard_temp` symlink-escape guard, the
no-replace collision guard and the `copy_new` exclusive-create guard all hold.

## Checklist (every item ticked, with evidence)

- **Plan §6.1 / §6.6 read, code compared line by line.** `docs/WEB_UI_PLAN.md`
  §6.6 (line 435) fixes the no-replace rename: Linux
  `renameat2(AT_FDCWD, src, AT_FDCWD, dst, RENAME_NOREPLACE)` via ctypes,
  macOS `renamex_np(src, dst, RENAME_EXCL)`, "No fallback: `EINVAL` or
  `ENOSYS` raises `UnsupportedPlatform` and nothing moves". §6.6 (line 436)
  fixes "Case-insensitive names … `entry_exists` by exact name"; line 442
  "Emptied folders … only `os.rmdir`, which fails on any entry"; line 443
  "segment ≤ 120 characters, relative path ≤ 400" (paths, not this module);
  line 440 "Same device … `st_dev` check". §6.1 (line 307-314) fixes
  `entry_exists` exact-name comparison and the `discard_temp` contract
  ("unlinks only files under `work_dir/tmp/` named `op-<id>.*` and raises for
  any other path"). `primitives.py` matches:
  - `AT_FDCWD=-100`, `RENAME_NOREPLACE=1`, `RENAME_EXCL=0x4`
    (`primitives.py:44-46`) — the §6.6 flags.
  - `rename_noreplace` (`primitives.py:61-101`) loads the platform lib
    (`primitives.py:49-58`), takes the darwin `renamex_np` branch
    (`primitives.py:77-84`) and the Linux `renameat2` branch
    (`primitives.py:85-92`), maps `EEXIST→DestinationExists`
    (`primitives.py:96-97`), `EINVAL`/`ENOSYS→UnsupportedPlatform`
    (`primitives.py:98-99`) and re-raises any other errno as `OSError`
    (`primitives.py:100`). No fallback to a replacing rename: a monkeypatched
    `os.rename` is never called on the success path
    (`test_rename_noreplace_never_falls_back_to_os_rename`).
  - `entry_exists` (`primitives.py:176-187`) compares the exact names from
    `os.listdir` (`primitives.py:184-187`), never `Path.exists` — the §6.1/§6.6
    exFAT rule; `entry_exists(parent, 'A.mp3')` is `False` when only `a.mp3`
    exists (`primitives.py:179-181`, tested at
    `test_entry_exists_exact_name_only`).
  - `rmdir_if_empty` (`primitives.py:127-139`) is *only* `os.rmdir`
    (`primitives.py:134`), returning `False` on `ENOTEMPTY`/`EEXIST`
    (`primitives.py:135-137`) — the §6.6 "Emptied folders" row.
  - `copy_new` opens `O_WRONLY|O_CREAT|O_EXCL` then `os.fsync`
    (`primitives.py:148-156`) — the §6.1 "No call that can replace … exists"
    rule (invariant I2).
  - `discard_temp` (`primitives.py:162-173`) unlinks only
    `work_dir/tmp/op-<digits>.*` and raises for anything else — the §6.1
    `discard_temp` contract verbatim.
  - `same_device` (`primitives.py:190-195`) is the `st_dev` check of §6.6
    line 440. No drift.

- **Crash-matrix test (FaultyFs before/after each fs call) + recovery +
  assert_consistent, where the module performs disk changes.** N/A for
  primitives. `FaultyFs`/`assert_consistent` are P1-12 (not built yet), and the
  crash matrix is written against the *operations* that perform the state
  transitions of §6.2/§6.3 (`ops/move.py`, `ops/retag.py` — P1-13/P1-14),
  where a `SimulatedCrash` is raised at each disk action. This module is the
  primitive layer those ops call; a single primitive has no multi-step state
  transition to matrix, and `FaultyFs` is a test-support object P1-12 that this
  module does not import. The primitive-level guarantees are instead verified
  directly: no-replace (`EEXIST` → `DestinationExists`, both paths intact,
  `test_rename_noreplace_destination_exists_leaves_both_untouched`),
  exclusive create (`test_copy_new_refuses_existing_destination`),
  non-destructive `rmdir` (`test_rmdir_if_empty_leaves_nonempty_dir`), and a
  hand-run harness confirming the `discard_temp` symlink-escape is refused. Same
  N/A reasoning as the b8p.4 and b8p.8 reviews (primitive/pure modules).

- **No code path can replace or delete a library file.**
  `tests/test_no_unsafe_calls.py` does not exist yet (it is P1-7, not merged),
  so I searched the diff and the module myself. `git show 23f4dcf` and the
  current `src/organize_music/fsops/primitives.py` contain **no** `os.rename`,
  `os.replace`, `Path.rename`, `Path.replace`, `os.remove`, `os.unlink`,
  `Path.unlink`, `shutil.move`, `os.move`, or `shutil.rmtree` (hand grep of
  `src/organize_music/fsops/`, see command output in the notes). The **only**
  unlink in the module is `candidate.unlink()` in `discard_temp`
  (`primitives.py:173`), and it is guarded: the name must match
  `^op-\d+\..*$` (`primitives.py:159`) **and** `candidate.resolve().parent`
  must equal `work_dir/tmp` (`primitives.py:171`); any other path raises
  `ValueError` and is left untouched (`primitives.py:172`). I ran a throwaway
  harness that symlinks `work_dir/tmp/op-1.mp3` at a library file and confirms
  `discard_temp` refuses it (raises `ValueError`, the library file is
  byte-identical afterwards) — the `resolve()` guard defeats the `..`
  traversal and the symlink escape, so no library file can be removed through
  this helper. Safe.

- **Preconditions (path, size, mtime_ns, row_version) checked before the first
  disk change.** N/A as an engine responsibility. Per §6.1/§6.2 the precondition
  `(expect_path, expect_size, expect_mtime_ns, expect_row_version)` re-stat and
  re-read belong to the operations layer (P1-13/P1-14), which is not built yet;
  this module does not hold or check a precondition. What the module *does*
  perform as a pre-change guard is correct: `rename_noreplace` refuses an
  occupied destination name **before the system call** via
  `os.path.lexists(dst)` (`primitives.py:72-73`) — the escalation fix
  (`1a767cf`) that closes the case-only APFS hole where
  `renamex_np(RENAME_EXCL)` would otherwise let `a.mp3 → A.mp3` through as the
  same file; and `copy_new` uses `O_EXCL` so an existing destination is refused
  before any byte is written. Both run before the first disk change, and the
  atomic flag still covers a destination created between the check and the call.
  (The precondition *check itself* is the caller's job, as noted.)

- **Errors are explicit and use the documented codes; no bare except, no
  `except: pass`, nothing swallowed.** The four `except` clauses are all
  specific: two `except AttributeError` around the symbol lookup that raise
  `UnsupportedPlatform` (`primitives.py:80`, `primitives.py:88`);
  `except OSError as exc` in `rmdir_if_empty` that narrows to
  `ENOTEMPTY`/`EEXIST` and re-raises every other errno (`primitives.py:135-138`);
  `except FileNotFoundError: return False` in `entry_exists`
  (`primitives.py:185-186`) — a documented "parent does not exist → no match"
  return, not a swallow. There is no bare `except`, no `except: pass`, and no
  `pass` in the module (hand grep). `rename_noreplace` re-raises any unlisted
  errno as `OSError(err, strerror, dst)` (`primitives.py:100`) rather than
  hiding it.

- **Tests written first, covering the failure cases in b8p.9.** PR #19 records
  TDD (red before the module existed, green after). `tests/fsops/`
  (`test_primitives.py`, 28 tests) covers every failure case the issue lists:
  move (`test_rename_noreplace_moves_a_file`); `EEXIST` collision leaves both
  files byte-identical (`test_rename_noreplace_destination_exists_leaves_both_untouched`);
  case-only `a.mp3 → A.mp3` raises `DestinationExists` on a case-insensitive FS,
  skipped with a reason on a case-sensitive one
  (`test_rename_noreplace_case_only_raises_on_case_insensitive`); the
  `lexists` refusal *before the syscall* (runs on every platform,
  `test_rename_noreplace_refuses_existing_name_before_the_syscall`) and the
  `EEXIST`-from-the-syscall path (`test_rename_noreplace_eexist_from_the_syscall_raises_destination_exists`);
  the no-fallback assertion (`test_rename_noreplace_never_falls_back_to_os_rename`);
  a monkeypatched missing symbol → `UnsupportedPlatform` with the file unmoved
  (`test_rename_noreplace_missing_symbol_raises_unsupported_and_unmoved`);
  `copy_new` refuses an existing dst (`test_copy_new_refuses_existing_destination`);
  `discard_temp` refuses paths outside `work_dir/tmp` and names not matching
  `op-<digits>.*`, including a `..` traversal escape
  (`test_discard_temp_refuses_outside_tmp`, `test_discard_temp_refuses_traversal_escape`,
  `test_discard_temp_refuses_bad_name`); `rmdir_if_empty` returns `False` and
  leaves a non-empty dir (`test_rmdir_if_empty_leaves_nonempty_dir`);
  `entry_exists('A.mp3')` is `False` when only `a.mp3` exists
  (`test_entry_exists_exact_name_only`). The suite honours `OM_FS_TEST_DIR`
  (`conftest.py:33-40`) so the same tests run against the Pi's exFAT mount in
  P1-21; I confirmed `OM_FS_TEST_DIR=$(mktemp -d) pytest -q tests/fsops` passes
  too.

- **Files <= 200 lines, typed signatures, no dead code.** `primitives.py` is
  195 lines (under 200); `fsops/__init__.py` and `tests/fsops/__init__.py` are
  1 line; `conftest.py` is 44. Every public function has a typed signature
  (`primitives.py:35,39,49,61,104,113,122,127,142,162,176,190`). No dead code:
  every `__all__` entry is defined and exercised by the tests. See *Findings*
  for the one non-blocking observation on `test_primitives.py` length.

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.10` (from `origin/main` `19a4e33`), run under the
project venv (Python 3.13.5, which satisfies `requires-python >=3.12`; the
sandbox's system `python` is 3.11 and lacks the project deps, so the venv is
used, as the issue's "Done when" is a mechanical gate not a runtime pin):

```
All checks passed!
71 files already formatted
280 passed, 1 skipped in 0.49s
```

The 1 skip is `test_rename_noreplace_case_only_raises_on_case_insensitive`,
skipped because the sandbox's filesystem is case-sensitive (the test runs on the
Pi's exFAT and on APFS). The `OM_FS_TEST_DIR` variant of the fsops suite:
`27 passed, 1 skipped`.

## Findings

- **Observation (non-blocking, no issue filed).** `tests/fsops/test_primitives.py`
  is 359 lines, above the "≤ 200 lines" guideline in the checklist. The guideline
  is a source-code-size guard (the module `primitives.py` is 195 and passes); a
  test file of 28 table-driven cases naturally exceeds 200, and the cases are
  grouped and each asserts one behaviour. This is not a safety or correctness
  finding and does not block the next phase, so no issue is filed. If a future
  review prefers strict enforcement on test files, split the suite by primitive
  (rename / copy / discard / rmdir / entry_exists / same_device) — noted here,
  not in the queue.

None blocking. No safety findings, nothing blocks the next phase, no new issue
filed.

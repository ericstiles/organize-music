# Review: paths.py — safe relative paths and exFAT collision keys (organize_music-b8p.8)

Paired review of `organize_music-b8p.7` (PR #23, merge commit `47758d5`), which
added `src/organize_music/paths.py` and `tests/test_paths.py`: the only path
constructor the web engine accepts, plus the case-insensitive exFAT collision
key. Catalogue id P1-5-R.

Reviewer: Hermes run `20261120_230213_335e8d`.

## Verdict

**Approve.** No safety findings. Nothing blocks the next phase; no new issue
filed.

## Checklist (every item ticked, with evidence)

- **Plan §9.4 / §6.6 read, code compared line by line.** `docs/WEB_UI_PLAN.md`
  §9.4 "Paths" (line 605-608) requires `paths.resolve_target(root, rel)` to
  "reject absolute paths, `..`, empty segments, and NUL … joins under the root,
  walks each existing component with `lstat`, rejects symlinks, and checks that
  `realpath` is inside the root"; §6.6 "exFAT specifics" (line 443) fixes
  "segment ≤ 120 characters, relative path ≤ 400" and §6.6 "Unicode" (line 439)
  "comparisons on NFC + casefold". `paths.py` matches:
  - `MAX_SEGMENT = 120`, `MAX_PATH = 400` (`paths.py:20-21`) — the §6.6 length row.
  - `validate_relative` (`paths.py:38-62`) rejects a non-string (`paths.py:43-44`),
    the empty string (`paths.py:46-47`), an absolute path (`paths.py:48-49`), a
    `.`/`..` or empty segment (`paths.py:55-57`), a NUL/control char
    (`paths.py:50-51`), a segment `> MAX_SEGMENT` (`paths.py:58-59`) and a total
    `> MAX_PATH` (`paths.py:53-54`), returning an NFC-normalised
    `PurePosixPath` (`paths.py:45`, `61`). This is exactly the §9.4 reject list.
  - `resolve_target` (`paths.py:83-97`) validates first (`paths.py:85`), joins
    under `root` (`paths.py:86`), `lstat`s each existing intermediate component
    and raises on a symlink (`_refuse_symlinks`, `paths.py:76`, `79`), then
    requires `realpath(target)` inside `realpath(root)` via `_is_within`
    (`paths.py:33-35`, `95`) — the final-component symlink is caught by this
    backstop since it has no intermediate to `lstat`. Matches §9.4 verbatim.
  - `path_key` is `unicodedata.normalize("NFC", rel).casefold()`
    (`paths.py:28-30`); `is_case_only` is `a != b and path_key(a) == path_key(b)`
    (`paths.py:100-102`) — the §6.6 NFC+casefold comparison. No drift.

- **Crash-matrix test (FaultyFs before/after each fs call) + recovery +
  assert_consistent, where the module performs disk changes.** N/A. This module
  performs **no library-file disk change**: its only filesystem call is the
  read-only `os.lstat` in `_refuse_symlinks` (`paths.py:76`); everything else is
  pure (`os.path.isabs`, `os.path.realpath`, `unicodedata`, string ops). A
  read-only `lstat`/`realpath` walk has no before/after state transition, so a
  crash matrix has no failure points. `FaultyFs`/`assert_consistent` are not
  built yet (P1-12) and are irrelevant here. Same N/A reasoning as the b8p.4
  review.

- **No code path can replace or delete a library file.** `tests/
  test_no_unsafe_calls.py` does not exist yet (it is P1-7, not merged), so I
  searched the diff myself. `git show 47758d5` and the current
  `src/organize_music/paths.py` contain no `os.rename`, `os.replace`,
  `Path.rename`, `Path.replace`, `os.remove`, `os.unlink`, `Path.unlink`,
  `shutil.move`, `os.move`, or `shutil.rmtree`. The only filesystem call is the
  read-only `os.lstat` (`paths.py:76`) used to *detect and reject* symlinks; the
  module returns a joined path and writes nothing. Safe.

- **Preconditions (path, size, mtime_ns, row_version) checked before the first
  disk change.** N/A. This module changes no file, so there is no "first disk
  change" to gate. Precondition checking belongs to the move/retag ops (P1-13/
  P1-14) that consume these paths later. (`validate_relative` is itself a
  precondition check the callers perform before a disk change, which is the
  module's job, and it does it correctly.)

- **Errors are explicit and use the documented codes; no bare except, no
  `except: pass`, nothing swallowed.** `InvalidPath(ValueError)` is the only
  exception (`paths.py:24`), raised with a specific message at every reject site
  (`paths.py:44, 47, 49, 51, 54, 57, 59, 80, 95`). The single `except
  FileNotFoundError: continue` in `_refuse_symlinks` (`paths.py:77`) is
  intentional and documented in the docstring: a not-yet-created intermediate
  component is skipped, and the `realpath` backstop (`paths.py:95`) still
  confirms the resolved path stays inside the root. It is a specific, intended
  "component does not exist yet" path, not a swallowed error, and it cannot
  bypass the escape check.

- **Tests written first, covering the failure cases in b8p.7.** PR #23 records
  TDD: red confirmed before the module existed (`ImportError: cannot import name
  'paths'`), green after. `tests/test_paths.py` (183 lines, 19 tests,
  table-driven) covers every failure case the issue lists: `/abs`, `../x`,
  `a/../b`, `a//b`, `""`, `a\x00b`, a 121-char segment and a 401-char path all
  raise `InvalidPath` (`test_validate_rejects_invalid`), control chars
  (`test_validate_rejects_control_chars`), the total-over-max-with-each-segment-ok
  case (`test_validate_rejects_total_over_max_each_segment_ok`), NFC normalisation
  (`test_validate_normalises_nfc`, `test_path_key_nfc_normalised`),
  `path_key("A/B.mp3") == path_key("a/b.MP3")`, a symlinked intermediate dir
  pointing outside root (`test_resolve_rejects_symlink_dir_pointing_outside`),
  a symlink final component pointing outside root
  (`test_resolve_rejects_symlink_final_component_outside`), and the `is_case_only`
  true/false cases. Branch coverage on the module is 100% per PR #23.

- **Files <= 200 lines, typed signatures, no dead code.** `paths.py` is 102
  lines; `tests/test_paths.py` 183. All public functions have typed signatures
  (`paths.py:28, 33, 38, 65, 83, 100`). No dead code: every function is used by
  the tests and the module is the path constructor named in §9.4.

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.8` (from `origin/main` `33a6b80`):

```
All checks passed!
70 files already formatted
280 passed, 1 skipped in 0.46s
```

## Findings

None. No safety findings, nothing blocks the next phase, no new issue filed.

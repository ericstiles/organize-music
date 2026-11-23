# Review: Files repository — compare-and-set path update

Paired review of `organize_music-b8p.14` (**Files repository: compare-and-set
path update**, catalogue id **P1-9**, merged as PR #47, commit `727c3dc`, now on
`main` at `58a3893`). The review target is the code as it is on `main` after
b8p.14 landed: the new module `src/organize_music/db/files_write.py` (67 lines)
plus its test module `tests/db/test_files_write.py` (125 lines), both added by
`727c3dc` and untouched by the later `ddabd7f` (b8p.28) / `58a3893` (bv recipe)
commits on the same branch. Catalogue row P1-9; this is the P1-9-R review
issue.

Reviewer: Hermes run `20261122_192722_24ba49` (**model qwen3.8-27**). The issue
carries the label `model:opus-5.5` (the review was assigned to Claude Opus 5.5);
this run is performed by qwen3.8-27, so there is a model mismatch to flag here,
mirroring how b8p.6 (also `-R`, `model:opus-5.5`) was itself reviewed by
qwen3.8-27 and noted the mismatch explicitly. The mismatch is cosmetic only —
the checklist is model-independent — and does not affect the verdict.

## Verdict

**Approve.** No safety findings. Nothing blocks the next phase (P1-22, the
*Move operation execution* that this review gates via `b8p.15 → b8p.22`), and no
new issue is filed. The one function under review, `files_write.update_path`, is
correct and safe: it is a single atomic compare-and-set `UPDATE` that performs
**no filesystem call whatsoever**, it commits nothing (the caller owns the
transaction, as the bead requires), its two failure modes raise the exact
documented exceptions and leave the row untouched, it carries no bare `except`
and swallows nothing, and every named failure case from b8p.14 is covered by a
purpose-built test that the gate runs green.

The review re-read PLAN §6.1 (the rules every mutation step follows) and §6.2
(the move operation's `applied → committed` row), compared them to the merged
code line by line, hand-searched `files_write.py` and the whole
`src/organize_music` tree for every forbidden filesystem call, and ran the
project's quality gate on this branch.

## What the module does (and why the checklist items scope the way they do)

`update_path` performs the committed move's **row update only** — PLAN §6.2's
`applied → committed` step, "DB: `path`, `path_key`, `row_version+1`, op
`committed` in one transaction", of which this module supplies the "DB: `path`,
`path_key`, `row_version+1`" half plus the bookkeeping columns `last_path`,
`size`, `mtime_ns`, `updated_at`. The "op `committed` in one transaction" half is
explicitly **out of scope** for this module (b8p.14: "No transaction management;
the caller wraps it with the op state change"), and the disk move itself
(`rename_noreplace`, `fsync`) is built later, in P1-22. So this module is the
database half of one step of a much larger journaled operation.

Crucially, `update_path` has **no disk side effect**. Its body is a single
`conn.execute("UPDATE files SET … WHERE file_id = ? AND row_version = ? AND
status = 'present'")` and the pure-Python `paths.path_key` helper (NFC-normalise
then `casefold`). It imports only `sqlite3` and `organize_music.paths.path_key`;
it imports no `os`, no `shutil`, no `FsOps`. The FaultyFs crash matrix (PLAN
§11) exists to prove that *disk actions* are crash-resilient and repeatable; a
pure SQL `UPDATE` inside a caller-owned transaction has no fs call to inject a
crash into, and — by the same logic the b8p.6 and b8p.12 reviews used for the
migration runner and the support/primitive modules — the crash-matrix checklist
item is therefore **N/A for this module**. The crash-resilience that *does*
matter here is the atomicity of the single `UPDATE`, which SQLite gives for free,
and which the `test_update_path_does_not_commit` test exercises by reading the
row back through a second connection.

## Checklist (every item ticked, with evidence)

### 1. Read the plan sections quoted in b8p.14 and compare the code line by line

- **b8p.14's spec** (verbatim, its "What to do" section): add `db/files_write.py`
  (keeping `files_repo.py` small) with `class StaleRow(Exception)`,
  `class PathTaken(Exception)`, and
  `def update_path(conn, file_id: int, expect_row_version: int, new_path: str,
  size: int, mtime_ns: int, now: str) -> None` doing
  `UPDATE files SET path=?, path_key=?, last_path=?, size=?, mtime_ns=?,
  row_version=row_version+1, updated_at=? WHERE file_id=? AND row_version=?
  AND status='present'`; rowcount 0 → `StaleRow`; `IntegrityError` on `path_key`
  → `PathTaken`; does not commit.
- **The code** (`files_write.py:38-67`) matches that spec **exactly**, including
  the parameter order, the `path_key` being computed via `paths.path_key(new_path)`
  (`files_write.py:56`), the `row_version = row_version + 1` bump, the three-way
  `WHERE file_id = ? AND row_version = ? AND status = 'present'` guard
  (`files_write.py:61`), the `IntegrityError → PathTaken` catch with `from exc`
  (`files_write.py:64-65`), and the `rowcount == 0 → StaleRow`
  (`files_write.py:66-67`). `files_repo.py` is untouched by `727c3dc` (the
  commit's stat is exactly `files_write.py +67`, `test_files_write.py +125`), so
  "keep files_repo.py small" holds: `files_repo.py` stays at its pre-b8p.14 size
  and the new write path lives in its own module.
- **PLAN §6.2** `applied → committed` row ("DB: `path`, `path_key`,
  `row_version+1`, op `committed` in one transaction") is realised by the
  `SET path = ?, path_key = ?, … row_version = row_version + 1` plus the
  `updated_at`/`last_path`/`size`/`mtime_ns` bookkeeping; the "op `committed` in
  one transaction" is the caller's half (out of scope, as b8p.14 states).
  PLAN §6.1 (every disk action repeatable, preconditions re-checked, no unsafe
  call) is satisfied by design — see items 3 and 4.

### 2. Every state transition has a crash-matrix test (FaultyFs before/after each
fs call) followed by recovery and `assert_consistent`, **where the module
performs disk changes**

**N/A — the module performs no disk change.** `files_write.py` imports neither
`os`, `shutil` nor `FsOps`; its only I/O is `conn.execute` on a single
`UPDATE` and the pure `paths.path_key` (NFC + `casefold`, `paths.py:30`). There
is no fs call for `FaultyFs` (tests/support/faulty_fs.py, PLAN §11) to inject a
crash into, and no disk mutation for `assert_consistent`
(tests/support/invariants.py) to re-check. This is the same scoping the b8p.6
(migration runner) and b8p.12 (crash-test support) reviews used: the crash
matrix has nothing to drive yet for a pure-SQL module, and the relevant
crash-resilience guarantee — atomicity of the `UPDATE` — is discharged by
`test_update_path_does_not_commit` (`test_files_write.py:76-88`), which reads
the row back through a *second* connection and asserts the update is not visible
until the caller commits. The journaled move that *does* perform the disk work
(the crash matrix's real subject) is P1-22, which this review gates via
`b8p.15 → b8p.22`. No crash-matrix gap is filed because there is no disk
transition to cover.

### 3. No code path can replace or delete a library file: `tests/test_no_unsafe_calls.py`
passes and you searched the diff yourself

- `tests/test_no_unsafe_calls.py::test_no_unsafe_filesystem_calls_outside_fsops`
  **passes** in the gate run below (366 passed).
- Hand-search of `src/organize_music/db/files_write.py` for
  `os.rename / os.replace / os.remove / os.unlink / os.rmdir / shutil.move /
  shutil.rmtree / .rename( / .replace( / .unlink( / Path.remove` →
  **no matches** (the only `.` method calls on line 62 are `path_key` and
  `conn.execute`; there is no `str.replace`/`Path` call at all).
- A repository-wide grep of `src/` for the forbidden forms outside `fsops/`
  finds nothing in `files_write.py`; the only sanctioned exceptions
  (`markdown.py` `str.replace`, `fsops/protocol.py` `os.replace`) are unchanged
  and recorded in the test module. I7 ("Library files are never replaced or
  deleted") is satisfied: the module writes only to the `files` *table*, never
  to a library *file*.

### 4. Preconditions (path, size, mtime_ns, row_version) are checked before the
first disk change

**N/A — there is no disk change, so there is no "before the first disk change"
window to check.** The compare-and-set *is* the precondition guard: the single
`UPDATE … WHERE file_id = ? AND row_version = ? AND status = 'present'`
(`files_write.py:58-63`) makes the write conditional on the row's `row_version`
still matching the caller's `expect_row_version` and on `status` still being
`'present'`, in the same atomic statement. Because the check and the write are
one SQLite statement, the guard **cannot race** with a concurrent writer in the
way a read-then-write could: there is no separate pre-read step. (The PLAN §6.1
"re-stat the disk and re-read the row before `intent`" step is the *move
op's* job, P1-22; by the time `update_path` runs the precondition has already
been established by the engine and is enforced here by the `row_version`
compare-and-set.) A stale `row_version` or a non-`'present'` status yields
`rowcount == 0` and raises `StaleRow` with the row left unchanged
(`files_write.py:66-67`), proved by `test_update_path_wrong_row_version_…`
(`:91-98`) and `test_update_path_missing_status_…` (`:101-112`).

### 5. Errors are explicit and use the documented codes; no bare except, no
`except: pass`, nothing swallowed

- Two explicit, documented exceptions: `StaleRow` (`files_write.py:24-28`,
  "the row's `row_version` no longer matches, or it is not `'present'`") and
  `PathTaken` (`files_write.py:31-35`, "the new `path_key` already belongs to
  another row").
- The only `except` in the module is `except sqlite3.IntegrityError as exc:`
  re-raising `PathTaken(...) from exc` (`files_write.py:64-65`) — a specific,
  named catch that preserves the chain (`from exc`), not a bare or
  `except: pass` swallow.
- A repository-wide grep of `src/` for `except\s*:` (bare except) returns
  **no matches**, and `files_write.py` contains no `except …: pass` and no
  swallowed error. Every refuse path raises a named exception with a message
  naming the file id / path.

### 6. Tests were written first and cover the failure cases listed in b8p.14

b8p.14's "Tests to write first" lists four cases; all four (plus a
commit-isolation case) are present in `tests/db/test_files_write.py`:

- **happy path** — bumps `row_version` and changes `path_key`:
  `test_update_path_happy_path_bumps_row_version_and_key` (`:58-73`), asserting
  `path`, `path_key`, `last_path`, `size`, `mtime_ns`, `row_version == 2`,
  `updated_at`, `status == 'present'`.
- **wrong `expect_row_version` → `StaleRow`, row unchanged**:
  `test_update_path_wrong_row_version_raises_stale_and_leaves_row_unchanged`
  (`:91-98`), asserting `row_state == ("a/one.mp3", 1, 1024)` after.
- **`path_key` collision → `PathTaken`, row unchanged**:
  `test_update_path_path_key_collision_raises_path_taken_and_leaves_row_unchanged`
  (`:115-125`), using exFAT case-insensitivity — moving to `"B/TWO.MP3"`
  collides with an existing `"b/two.mp3"` (both `path_key`-casefold to
  `"b/two.mp3"`), and the row is left unchanged.
- **`status` `'missing'` → `StaleRow`, row unchanged**:
  `test_update_path_missing_status_raises_stale_and_leaves_row_unchanged`
  (`:101-112`).
- Plus **`test_update_path_does_not_commit`** (`:76-88`), proving the module
  commits nothing (the caller owns the transaction) by reading the row back via
  a second connection.

All five pass in the gate run below.

### 7. Files are ≤ 200 lines, typed signatures, no dead code

- `src/organize_music/db/files_write.py` is **67 lines**;
  `tests/db/test_files_write.py` is **125 lines** — both well under the 200-line
  cap (CLAUDE.md guardrail).
- `update_path`'s signature is fully typed
  (`files_write.py:38-46`); the two exception classes and the module are typed
  via `from __future__ import annotations`. `files_write.py` imports only what it
  uses (`sqlite3`, `paths.path_key`); no dead code, no unused imports (the gate's
  `ruff check` passes, which enforces both).

## Quality gate (run on this branch, `58a3893`)

```
$ .venv/bin/ruff check .
All checks passed!
$ .venv/bin/ruff format --check .
93 files already formatted
$ .venv/bin/pytest -q
366 passed, 1 skipped, 2 warnings in 3.26s
```

The two warnings are a pre-existing `yoyo-migrations` `DeprecationWarning` about
the sqlite3 default datetime adapter, unrelated to this module (surfaced through
`test_files_repo.py`, which `migrate`s the schema). No new warning is introduced
by `files_write.py`.

## Findings

**None.** No safety finding, no bug, no gap. No new issue is filed. The module
satisfies the P1-9 spec exactly, the crash-matrix and precondition items are
correctly N/A for a pure-SQL writer (with no disk transition to cover), and the
next-phase gate (`b8p.15 → b8p.22`, *Move operation execution*) is unblocked by
this review.

### Nits (not filed — no test change, no behaviour impact)

- `PathTaken` relies on the partial unique index
  `files_path_key ON files(path_key) WHERE path_key IS NOT NULL`
  (`migrations/0001_initial.sql`) to detect the collision and translate its
  `IntegrityError` into `PathTaken`; the module does not pre-check the key
  itself. This is by design ("IntegrityError on `path_key` → `PathTaken`",
  b8p.14) and is correct, but it means a caller that wants to *know* a path is
  taken before attempting the write must query the index (e.g.
  `FilesRepo.get_by_key`, b8p.13) — a natural use of the reader repo, not a
  defect here.
- A `rowcount == 0` from a **nonexistent `file_id`** also raises `StaleRow`
  (same branch as a stale `row_version`). That is the intended "nobody may have
  changed the row" semantics, but a caller could not distinguish "stale" from
  "no such row" from the exception alone. Not a defect: the move op always
  operates on a row it just read, so a missing id would itself be a stale
  precondition. Noted only for the P1-22 author.
- Neither nit changes the verdict or blocks the next phase.

## Conclusion

**Approve `organize_music-b8p.14` (PR #47).** No findings, no new issues,
nothing blocks P1-22. The paired review is closed with the checklist ticked
above and the quality gate green.

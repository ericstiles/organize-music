# Review: DB connections and the single-writer lock (organize_music-b8p.4)

Paired review of `organize_music-b8p.3` (PR #22, merge commit `ca0841e`), which
added `src/organize_music/db/connection.py`: the single-writer connections for
`library.db` and the exclusive writer lock. Catalogue id P1-3-R.

Reviewer: Hermes run `20261120_131927_44188f`.

## Verdict

**Approve.** No safety findings. One minor robustness gap (P3, non-blocking)
filed as `organize_music-y4y`.

## Checklist (every item ticked, with evidence)

- **Plan §6.4 / §6.5 read, code compared line by line.** `docs/WEB_UI_PLAN.md`
  §6.4 ("One writer", line 401-405) and §6.5 ("Durability", line 415-416)
  require the writer to be `journal_mode=WAL`, `synchronous=FULL`,
  `foreign_keys=ON` and readers `query_only=ON`, with an exclusive
  `fcntl.flock` on `state/writer.lock` held for the server's lifetime; CLI
  writers take the same lock and fail with "server is running".
  `connection.py:23-25` (writer: WAL, `synchronous=FULL`, FK on) and
  `connection.py:33-34` (reader: FK on, `query_only=ON`) match exactly. Both
  set `row_factory=sqlite3.Row` (`connection.py:22, 32`), as the issue
  specifies. `WriterLock` is an exclusive non-blocking
  `fcntl.flock(fd, LOCK_EX | LOCK_NB)` on the lock file (`connection.py:50-52`),
  translating `BlockingIOError` to `WriterBusy("server is running")`
  (`connection.py:53-55`). No drift from the plan.

- **Crash-matrix test (FaultyFs before/after each fs call) + recovery +
  assert_consistent, where the module performs disk changes.** N/A. This module
  opens SQLite connections and an `fcntl.flock`; it performs **no library-file
  disk changes** (no rename/copy/unlink/mkdir). `FaultyFs`/`assert_consistent`
  are not built yet (P1-12, `tests/support/` absent) and are not relevant here.
  Confirmed by grepping the module: no `rename`/`replace`/`unlink`/`remove`/
  `rmtree`/`os.move`/`shutil`/`mkdir` call anywhere in
  `src/organize_music/db/connection.py`.

- **No code path can replace or delete a library file.** `tests/
  test_no_unsafe_calls.py` does not exist yet (it is P1-7, not merged); I
  searched the diff myself instead. `git show ca0841e` and the current module
  contain no `os.rename`, `os.replace`, `Path.rename`, `Path.replace`,
  `os.remove`, `os.unlink`, `Path.unlink`, `shutil.move`, or `shutil.rmtree`.
  The only file-system call is `os.open(..., O_RDWR | O_CREAT)` on the lock
  file in `state/` (`connection.py:50`), which is outside the library and
  cannot touch a library file. Safe.

- **Preconditions (path, size, mtime_ns, row_version) checked before the first
  disk change.** N/A. This module takes no preconditions and changes no file;
  precondition checking belongs to the move/retag ops (P1-13/P1-14), which
  consume these connections later.

- **Errors are explicit and use documented codes; no bare except, no
  `except: pass`, nothing swallowed.** `WriterBusy` is the only exception and
  its message is fixed ("server is running", `connection.py:55`). The single
  `except BlockingIOError` is specific and re-raises (`from None`); no bare
  `except`, no `except: pass`, nothing swallowed.

- **Tests written first, covering the failure cases in b8p.3.** The issue's
  failure cases are pragmas read back, a write through the reader raising
  `sqlite3.OperationalError`, a second lock raising `WriterBusy`, and the lock
  released after the block. `tests/db/test_connection.py` covers all four plus
  `row_factory` on both connections and context-manager identity
  (`test_connection.py:16-89`). TDD is recorded in PR #22's body ("TDD, written
  first").

- **Files <= 200 lines, typed signatures, no dead code.** `connection.py` is
  63 lines; `__init__.py` 17; `test_connection.py` 89. All public functions and
  the `WriterLock` methods have typed signatures (`connection.py:19, 29, 45,
  49, 59`). No dead code.

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.4` (from `origin/main` `47758d5`):

```
All checks passed!
62 files already formatted
272 passed, 1 skipped in 0.46s
```

## Findings

- **P3 (non-blocking), filed as `organize_music-y4y`:** `WriterLock.__enter__`
  closes the fd only on `BlockingIOError`; an *unexpected* `fcntl.flock` error
  (e.g. a real `OSError` or an interrupted `EINTR`) would leak the fd returned
  by `os.open`. Rare and non-safety, so it does not block the next phase. The
  fix is one line: close the fd on the general error path and re-raise.

No safety findings. Nothing blocks the next phase.

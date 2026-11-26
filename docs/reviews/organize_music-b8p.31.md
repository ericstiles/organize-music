# Review: Rename one file from the UI (journaled) (b8p.30)

Paired review of `organize_music-b8p.30` (the tracer's end-to-end mutation
through the web layer, plan §6.4/§9.4:
`src/organize_music/web/routes_rename_one.py`, `drafts.py`,
`rename_confirm.py`, the two templates, `tests/web/test_rename_one.py`, and
the `app.py` wiring; PR #73, rebase-merged as `21f9199` on 2026-11-26). The
review target is the code as it is on `origin/main` (`21f9199`). Catalogue id
P1-18-R.

Reviewer: Hermes run `20261125_214630_255d8f` (model
Youssofal/Qwen3.8-27B-MTPLX-Optimized-Speed). The issue carries the label
`model:opus-5.5`; this run used Qwen3.8-27B, so the verdict is offered for
the human reviewer to confirm under the intended model, not as a binding
Opus sign-off (recorded below as finding F-4, not a code finding). Same
situation as the b8p.25 review (its F-3) and the b8p.27 review (its F-2).

## Verdict

**Approve.** No safety findings, nothing blocks the next phase (b8p.32
"CLI: serve and recover commands", b8p.36 "End-of-phase review"). The
implementation matches b8p.30's contract line by line (table below), the
web layer performs **no filesystem calls of its own** — every disk action is
delegated to the already-reviewed, already-matrixed `run_move` (b8p.23) with
`RealFs` — drafts never touch `library.db` (plan §6.4), the precondition
re-checks happen before the first durable write at both layers, and the
error paths are explicit and logged. Three minor findings (F-1: a batch row
left `running` when the confirm raises or crashes; F-2: an unlogged
`except … : pass` in the reader plus 422 codes outside the plan §8
vocabulary; F-3: the preview stores the raw, non-NFC name) are filed as P3
issues; none is a safety finding and none blocks the next phase.

## What the code does (and how it maps to the plan and the contract)

`POST /files/{file_id}/rename` (`routes_rename_one.py:104-171`) validates
the hand-typed `new_name` (filename only, same folder), joins it under the
row's folder, checks it with `paths.validate_relative`, and stores a draft
batch plus one planned `move` op (with the row's `expect_*` tuple) in the
scratch `state_dir/drafts.db` (`drafts.save_draft`, `drafts.py:109-160`),
then re-renders the form as a preview (`rename_one.html`).
`POST /batches/{batch_id}/confirm` (`routes_rename_one.py:174-177` →
`rename_confirm.confirm`, `rename_confirm.py:57-75`) guards (mutations off
→ 403 `MUTATIONS_DISABLED`; unconfigured/uninitialised/lock → 503), takes
the writer lock, re-checks the draft's `expect_row_version` against
`library.db` (409 `PREVIEW_STALE` on mismatch), deletes the draft, copies
the batch and op into `library.db` in one transaction (`_copy_batch`,
`:126-150`), runs `run_move` synchronously (`:114-121`), settles the batch
(`_settle_batch`, `:153-164`) and renders `batch_result.html`.

Line-by-line against b8p.30's "What to do" and the plan sections it quotes
(§6.4 `WEB_UI_PLAN.md:381-388`, §9.4 `:592-611`):

| Contract element | Code | Match |
|---|---|---|
| "GET /files/{file_id}/rename shows a form with the current filename" | `routes_rename_one.py:82-101`; `rename_one.html` pre-fills `new_name` with the current basename (`:74`) | ✓ |
| "POST … validate with paths.validate_relative on the joined folder+new_name" | `:137-155` — filename-only slash guard first, then `validate_relative` on the join; 422 with the field message | ✓ (F-3: the NFC-normalised return value is discarded; the raw string is stored) |
| "create a draft batch (kind 'rename') with one move op (expect_* from the row)" | `drafts.save_draft` (`drafts.py:109-160`): batch `kind='rename' state='draft'` + op `kind='move' state='planned'` with `expect_path/size/mtime_ns/row_version` from the row (`routes_rename_one.py:158-168`) | ✓ |
| "render a preview page" | `_form_page` (`:62-79`) shows the from→to preview and the captured precondition; the confirm form posts to `/batches/{id}/confirm` (`rename_one.html`) | ✓ |
| "POST /batches/{batch_id}/confirm re-checks row_version (mismatch → 409 PREVIEW_STALE page)" | `rename_confirm.py:95-99` — re-read `files.row_version`, compare with the draft's `expect_row_version`, 409 + `PREVIEW_STALE` page; the draft is **not** consumed on this path so re-preview is possible | ✓ |
| "then runs run_move synchronously and shows the result" | `:103-123` — one-transaction copy into `library.db`, `run_move(op, ctx)` with `RealFs`, `_settle_batch`, `batch_result.html` with the outcome/error | ✓ |
| "Refuse when config.mutations_enabled is false with 403 MUTATIONS_DISABLED" | `:60-61` — first guard, before any connection; `app.py:41` reads `config.mutations_enabled` | ✓ |
| Plan §6.4: drafts live in `state_dir/drafts.db`, "never go into library.db" | `drafts.py:1-12, :24` (scratch schema mirroring migration 0001, FKs off because it holds no `files` table); proven by `test_preview_creates_a_draft_and_changes_nothing` (`test_rename_one.py:141-159`: zero batches/ops in library.db, row_version untouched) | ✓ |
| Plan §6.4: "If any differs, the job fails with PREVIEW_STALE, nothing is written, and the UI offers to re-preview" | nothing is written (draft kept, row untouched — `test_confirm_after_the_row_changed_is_409_preview_stale`, `:182-198`); the page says "re-preview" in the message, but offers no direct link on the error page (observation, below) | ✓ (UI micro-gap noted) |
| "Out of scope: filename only, same folder. No pattern, no job queue, no auth" | slash guard (`:137-147`); confirm is synchronous, no job enqueue; no auth code in the diff | ✓ |

No drift found. Two deliberate, documented simplifications of the full
plan: (1) confirm runs `run_move` synchronously in the request instead of
enqueueing a batch job (the job queue is P2-4, explicitly out of scope),
so plan §6.4's "errors that stop the batch" bookkeeping (batch →
`stopped`, `WEB_UI_PLAN.md:397-398`) is not yet applied — see F-1; (2) the
draft schema is a scratch mirror rather than shared tables, exactly as
§6.4 prescribes.

## Checklist (every item answered, with evidence)

- **Read the plan sections quoted in organize_music-b8p.30 and compared the
  code line by line.** b8p.30 quotes plan §6.4 ("preview then confirm") and
  §9.4 ("mutations off by default") in its Design. This run read
  `WEB_UI_PLAN.md` §6.1–§6.4 (`:298-412`), §8 (`:524-548`) and §9.4
  (`:592-611`); the mapping table above covers the full b8p.30 contract
  against the three new modules and the `app.py` diff with line
  references. The only boundary items (job queue, batch stop rules, auth)
  are explicitly later phases (P2-4) and outside b8p.30's "Files" scope —
  recorded, not a drift.

- **Every state transition has a crash-matrix test (FaultyFs before and
  after each fs call) followed by recovery and assert_consistent, where
  the module performs disk changes.** The web modules perform **no
  filesystem calls at all**: `drafts.py` is sqlite on the scratch DB only;
  `rename_confirm.py` passes `RealFs()` into `OpContext`
  (`rename_confirm.py:109`) and delegates every disk action to `run_move`;
  `routes_rename_one.py` opens read-only connections and calls
  `validate_relative` (pure, except the `lstat` walk in
  `resolve_target`, `paths.py:65-97`), which `run_move` then repeats. The
  disk-changing code is the already-reviewed `run_move` (b8p.23), whose
  committed crash matrix is `tests/ops/test_move.py:307-354`
  (`test_move_survives_a_crash_at_every_point`: measures the fs-call count
  clean, sweeps every point before+after under `FaultyFs`, asserts the
  content is at exactly one of `{src, via, dst}` and is never lost), with
  the recovery matrix in `tests/ops/test_recover_move.py` (b8p.25; its
  torn-recovery committed-test gap is the already-filed
  `organize_music-6yg`). The web layer's own durable writes are single
  atomic SQLite transactions, and its crash windows are documented in
  `rename_confirm.py:83-85` (delete-draft → copy: the draft is lost,
  nothing else changed, the user re-previews; copy → run_move: the op sits
  in `library.db` for startup recovery) and locked in by
  `test_confirmation_is_one_shot` (`:285-301`) plus the two
  exception-path tests below.

- **No code path can replace or delete a library file.**
  `pytest -q tests/test_no_unsafe_calls.py tests/test_file_length.py` →
  **4 passed** (part of the 488). A hand search of the PR #73 diff
  (`git diff f125293..21f9199 -- src/`, added lines) over the guard's own
  patterns (`os.rename(`, `os.replace(`, `os.remove(`, `os.unlink(`,
  `shutil.move(`, `shutil.rmtree(`, `.rename(`, `.replace(`, `.unlink(`)
  returned **zero matches in src/**; the only hits in the whole diff are
  the word "rename" in docstrings, template names and test names, plus
  `move._step` in `tests/web/test_rename_one.py:319-320` (test code
  driving the reviewed move module — not a filesystem call). `run_move`
  itself was cleared in b8p.23.

- **Preconditions (path, size, mtime_ns, row_version) are checked before
  the first disk change.** Two layers, both before any durable write.
  Web: `rename_confirm.py:95-99` re-reads `files.row_version` before the
  first write the confirm performs (the scratch-draft delete at `:100`;
  the first `library.db` write is the batch copy at `:103`; the first disk
  change is inside `run_move`). Op: `run_move`'s `planned` step
  (`move.py:59-90`) re-stats the source (`size`, `mtime_ns`,
  `move.py:64-70`) and re-reads the row (`status`, `row_version`,
  `:71-75`) before the first disk action (`_intent`'s `mkdir_one` /
  `rename_noreplace`, `:99-109`); a mismatch fails with
  `PRECONDITION_FAILED` and marks the row `changed` without moving the
  file (`:68, :70, :75, :188-196`), and the commit re-guards
  `row_version` as a compare-and-set
  (`files_write.update_path`, `move.py:137-140`). Locked in by
  `test_confirm_after_the_row_changed_is_409_preview_stale`
  (`test_rename_one.py:182-198`) and the move tests (b8p.23).

- **Errors are explicit and use the documented codes; no bare `except`, no
  `except: pass`, nothing swallowed.** The diff adds 8 `except` clauses
  (grep over `git diff f125293..21f9199`): `drafts.py:157`
  (`BaseException` → rollback + re-raise); `rename_confirm.py:46`
  (`sqlite3.Error` → `False`, the schema probe), `:53`
  (`JSONDecodeError/AttributeError` → `None`, the params probe), `:70`
  (`WriterBusy` → 503 page), `:116` (`Exception` → **warning log** +
  explicit "stopped with …; it will be recovered at the next startup"
  page), `:147` (`BaseException` → rollback + re-raise);
  `routes_rename_one.py:41` (**`sqlite3.Error` → `pass`** — the one
  unlogged, no-observable-effect swallow; finding F-2) and `:152`
  (`InvalidPath` → 422 with the field message). No bare `except:`
  anywhere (grep over the new files: none). The `except Exception` at
  `:116` cannot swallow `SimulatedCrash`, which subclasses
  `BaseException` (plan §6.1, `WEB_UI_PLAN.md:319-320`). Codes used:
  `MUTATIONS_DISABLED` (§9.4 `:610-611`), `PREVIEW_STALE` and `COLLISION`
  (§8 table `:529-531`) — the codes the plan documents for this flow.
  Deviations: the 422 validation uses `INVALID_NAME` where §8 documents
  `INVALID_INPUT`, and the guard pages use codes outside the §8 table
  (`NOT_FOUND`, `NOT_PRESENT`, `NOT_INITIALISED`, `LIBRARY_NOT_CONFIGURED`,
  `WRITER_BUSY`) — finding F-2.

- **Tests were written first and cover the failure cases listed in
  b8p.30 (collision, precondition failed, crash at each step).** b8p.30's
  notes record the TDD order: "PROGRESS: tests written (RED: 9 failed,
  2 passed) — implementing drafts + routes next". All six cases b8p.30
  listed to write first are present in `tests/web/test_rename_one.py`:
  preview creates a draft and changes nothing on disk (`:133-160`);
  confirm renames and the row's path updates (`:163-179`); confirm after
  the row changed → 409 (`:182-198`); `../x.mp3` → 422 (`:201-211`);
  target exists → COLLISION, nothing moved (`:235-248`); mutations
  disabled → 403 (`:221-232`). Five more are committed: a `/` in the
  name → 422 (`:214-218`), missing batch → 404 (`:264-267`), case-only
  renames committing through the via-temp route (`:251-261, :270-282`),
  one-shot confirmation (`:285-301`), and the two exception-position
  tests — `run_move` raising mid-move leaves the op `applied` with the
  page's recovery message and the draft consumed (`:304-342`), raising
  before any step leaves it `planned` (`:345-370`). The true
  before/after-`FaultyFs` sweep of the disk steps is the move crash
  matrix (`tests/ops/test_move.py:319`), as the web layer makes no fs
  calls of its own (second checklist item).

- **Files are <= 200 lines, typed signatures, no dead code.** `wc -l`:
  `drafts.py` **194**, `rename_confirm.py` **200** (exactly at the limit —
  no headroom, noted), `routes_rename_one.py` **177**, `app.py` **114**;
  `tests/web/test_rename_one.py` 370, outside the guard's scope
  (`tests/test_file_length.py:11-14` scans `src/organize_music` only and
  fails on `> 200`, so exactly 200 passes — the pending
  `organize_music-c6s` will codify the CI check the same way). Every
  signature in the three modules is typed (e.g.
  `confirm(request: Request, batch_id: int) -> Response`
  `rename_confirm.py:57`; `save_draft(...) -> int` `drafts.py:109-120`;
  `rename_preview(...) -> Response` `routes_rename_one.py:104-110`). No
  dead code: `Draft.op_values` is used by `_copy_batch`
  (`rename_confirm.py:144`), `_dst_of`/`_ctx` by `_render`
  (`:179, :187-200`), and the templates' fields are all read
  (`batch_result.html` renders `state`/`error_code`/`halted`/`error`).

## Quality gate

`ruff check . && ruff format --check . && pytest -q` on
`bd/organize_music-b8p.31` (branched from `origin/main` `21f9199`), run
under the project venv:

```
ruff check .          -> All checks passed!
ruff format --check . -> 126 files already formatted
pytest -q            -> 488 passed, 1 skipped, 4 warnings in 6.06s
```

The 1 skip is the case-sensitive-filesystem skip in
`tests/fsops/test_primitives.py:80` — pre-existing and unrelated. The 4
warnings are yoyo's deprecated default `datetime` adapter — pre-existing
and unrelated. The rename tests (15) are all green.

## Findings

None blocking. No safety findings: no filesystem call in the diff
(guard + hand search above), drafts never touch `library.db` (plan §6.4),
preconditions precede every durable write, and the disk work's own
crash/recovery matrices are committed (b8p.23/b8p.25). Three minor,
non-blocking findings, each filed as a P3 issue (discovered-from
`organize_music-b8p.31`):

- *F-1 (minor, plan deviation — batch bookkeeping): a failed confirm
  leaves the `library.db` batch row `running` forever.* The exception path
  (`rename_confirm.py:114-121`) returns before `_settle_batch` (`:122`),
  and a crash between `run_move`'s committed transition and the settle
  commit leaves the same state: the batch (inserted `'running'` at
  `:136`) is never settled, while its op is terminal. Verified by probe in
  this run (`/tmp/review_probe_b8p31.py`, probe 1): after a raised
  mid-move `run_move`, `batches` holds
  `{state: 'running', total: 0, succeeded: 0, failed: 0}` with the op
  `applied`; the startup recovery dispatcher (b8p.26/b8p.27) walks
  non-terminal **ops** only, so nothing settles the row. Plan §6.4
  (`WEB_UI_PLAN.md:397-398`) says an error that stops the batch makes the
  batch `stopped`. Not user-visible today (no batch result page in the
  tracer), but a latent inconsistency for the later batch UI/runner.
  Filed: P3 `organize_music-5yw` (discovered-from
  `organize_music-b8p.31`).
- *F-2 (minor, diagnostics/hygiene): one unlogged `except … : pass`, and
  error codes outside the plan §8 vocabulary.*
  `routes_rename_one.py:39-42` swallows `open_reader` failures with a bare
  `pass`, conflating "database not initialised" (expected on a fresh
  state) with "corrupt or unreadable database" (should surface), and logs
  nothing — the plan §8 logging rule (`WEB_UI_PLAN.md:545-547`) and the
  sibling `app.py:106-111` (`_db_ok` logs its probe failure) both point
  the other way; `rename_confirm.py:41-47` (`_schema_ok`) has the same
  unlogged-probe shape. Separately, the 422 validation code is
  `INVALID_NAME` where §8 documents `INVALID_INPUT` (`:528`), and the
  guard codes (`NOT_FOUND`, `NOT_PRESENT`, `NOT_INITIALISED`,
  `LIBRARY_NOT_CONFIGURED`, `WRITER_BUSY`) are not in the §8 table at
  all — the table either needs them or the code should say so.
  Filed: P3 `organize_music-y8t` (discovered-from
 `organize_music-b8p.31`).
- *F-3 (minor, plan deviation — NFC): the preview stores the raw typed
  name, discarding `validate_relative`'s NFC-normalised return value.*
  `routes_rename_one.py:149-151` builds `joined` from the raw form value
  and calls `validate_relative(joined)` for its side effect only; the
  draft stores `dst_rel=joined` raw (`:163`). Verified by probe in this
  run (probe 2): a decomposed (NFD) `songé.mp3` is stored in
  `params_json` as NFD — "stored dst already NFC: False" — while plan
  §6.6 (`WEB_UI_PLAN.md:439`) says "new names written NFC". Edge case
  (composing input from a browser), collision detection is unaffected
  (`path_key` normalises both sides), but the on-disk name should be the
  validated form.
  Filed: P3 `organize_music-0tc` (discovered-from
  `organize_music-b8p.31`).
- *F-4 (process): model label.* The issue is labelled `model:opus-5.5`
  (the intended paired reviewer), but this run was performed under
  Qwen3.8-27B (MTPLX-Optimized-Speed), exactly as the b8p.25 and b8p.27
  reviews were. The findings above are mechanical (contract mapping,
  proven guard, probes, diff searches), so they are model-independent;
  the label is recorded here so the sign-off is not mistaken for an Opus
  one. Not a code finding and not a blocker.

Observations (not filed): (1) the `PREVIEW_STALE` page says
"re-preview" in its message but offers no direct link
(`batch_result.html` hides the "Rename again" link when `error` is set);
the draft is kept, so re-preview needs two clicks via
`/files/{id}/rename` — plan §6.4's "the UI offers to re-preview" is
met in substance, not in the one-click sense. (2)
`rename_confirm.py` is exactly at the 200-line limit — any fix in F-1/F-2
territory that touches it should expect a split.

## Duplicate check

`bd list --all` (197 issues, checked at `origin/main` `21f9199`):
`organize_music-fcj` is the *move operation's* findings bundle
(`ops/move.py` cleanup logging, `CROSS_DEVICE` code, dead classes in
`ops/context.py`) — different files and different gaps than F-1/F-2/F-3;
`organize_music-6yg`/`h1e` are the recovery/dispatcher torn-matrix
coverage gaps (already filed by the b8p.25/b8p.27 reviews);
`organize_music-dnl.10` (batch runner: units, stop rules, cancel, a later
phase) will supersede the tracer's synchronous confirm but does not cover
the stuck-`running` row the tracer leaves *today*; no open issue covers
the `_reader` swallow or the NFC storage. Three new P3 issues are filed
(F-1, F-2, F-3) and no duplicate exists.

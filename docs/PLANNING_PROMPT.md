# Planning Prompt: Web UI Music Organizer on the Pi

Paste everything below the line into a fresh session started in
`/Users/wilder/repo/organize_music`. State described here was verified on
2026-11-16 at commit `2a9ee13` (branch `feat/phase2-naming-preview`).

---

You are taking over `organize_music` as the principal engineer. The project is mid-flight: a read-only CLI exists, a naming feature is half-landed on a broken branch, and the product goal has grown beyond what the existing plan and issue tracker describe. Your job in this session is to produce an approved plan and then turn it into beads issues that other sessions will implement one at a time. Do not implement features in this session.

## What we are building

A web application that runs on a Raspberry Pi 5 and manages a music library of roughly 100,000 mp3/m4a files on an exFAT SSD attached to that Pi. One owner uses it from a browser on the home LAN. It must:

1. Read audio files under a configured directory and show each file's name, location, and metadata.
2. Let the user change file names, and optionally file locations, either by applying a standard naming pattern (for example `${artist}/${album}/${track}-${title}.${ext}`) to a selection, or by editing one part by hand.
3. Let the user edit a single metadata value such as the artist, across one file or many. Such an edit may need to change the tags inside the files, the file names, and the folders they live in, and all of those must end up agreeing.
4. Show duplicates, grouped by a hash of the song.
5. Keep a database as the system of record for songs and files, including each file's current location and the history of changes made to it.

The files are the owner's only copy of this library. Losing a file, overwriting one, or leaving the database and the disk disagreeing after a crash are the failures that matter most. Design for them first.

## Where the project stands

Check each of these yourself before relying on it; the repo may have moved since this was written.

**Working on `main`:** CLI commands `meta`, `hash`, `dupes`, `tags`; a SQLite index (`index_db.py`, `hash_index.py`) with `tracks` and `hashes` tables; YAML config; `scripts/deploy_to_pi.sh`. Everything is read-only against the library. Pure logic is separated from side effects and `tag_reader.py` is the only module that imports mutagen.

**Broken on the current branch** (six commits ahead of `main`, nothing merged):

- `pytest` fails at collection and `ruff check` fails. Commit `057322a` removed `render_metadata_report` from `reports.py`, which `cli.py` and `tests/test_reports.py` still import. Commit `2a9ee13` removed `run_dupes` from `cli.py` while the `dupes` subparser still calls it.
- `rename --apply` in `cli.py` is a `TODO` that renames nothing, although issue `organize_music-cvf` is closed and `tests/test_cli_rename.py` asserts the file was renamed.
- `naming.render_name` does not call `sanitize`, there is no segment or path length cap, and `rename.transform_name` duplicates part of `sanitize`.
- `cli.py` is 225 lines against the repo's 200-line limit.

**Not started:** `journal.py` and `fileops.py` from `docs/PLAN.md`, any tag writing, any web server code or web dependency, the `names` and `organize` commands.

**Beads:** run `bd list --all`, `bd blocked`, and `bd show` on every open or in-progress issue. As of writing: `2k2` (naming preview) and `3d1` (web UI) are in progress with expired leases and `3d1` has no code; `z80`, `dpf`, `cpc`, `8su`, `hpg`, `p1b` are open. `docs/TASKS.md` is out of date against beads.

## Conflicts between the existing design and the new goal

The existing plan was written for a cautious CLI. Several of its decisions do not survive the new requirements. Resolve each one explicitly in the plan, with your recommendation and reasoning. Where the choice is a product decision rather than an engineering one, ask the owner.

1. **Cache versus system of record.** `index_db.py` treats the database as disposable: on a schema version mismatch it drops both tables. A system of record needs forward migrations, a backup story, and a defined answer to "the database is lost or corrupt; what do we rebuild from disk and what is gone?"
2. **Identity.** Rows are keyed by `(root, path)`, and `hashes` is keyed the same way separately. A rename currently looks like a delete and an insert. Decide on stable identifiers, and whether "song" (a recording) and "file" (one copy of it on disk) are separate entities, since duplicates are many files for one song.
3. **What "song hash" means.** Today only files that share a byte size get a whole-file MD5. Editing a tag changes the file's bytes, its MD5, and its mtime, so the first metadata edit through the UI would make two copies stop matching and invalidate the cached hash. Issue `8su` (hash of the audio payload, ignoring tag bytes) is filed as a later nice-to-have; decide whether it is now a prerequisite, whether every file gets hashed, and how hashes are kept valid after the tool itself modifies a file.
4. **Who may modify files.** `docs/PLAN.md` decision 4 says only the `organize` command renames and every other command is read-only. The UI now needs to rename, move, and retag. Define a single mutation path that both CLI and UI go through, and say what happens to `rename` (cvf), `organize` (dpf), and `quarantine` (cpc).
5. **Collision policy contradicts itself.** `docs/PLAN.md` says the tool never invents a suffix and leaves colliding files in place. The closed decision issue `3z4` says keep both with a `-copy-N` suffix. Pick one.
6. **Template is ambiguous.** `3z4` records `${track #}-${track}-${title}`; config and code use `${track}-${title}`. Pin the placeholder vocabulary and the default.
7. **Metadata edits versus field sources.** Each field records whether it came from a tag, the filename, the folder, or is missing. Decide what a user edit is (a new source? a tag write?), whether edits always write tags into the file, and what happens for formats where writing is unsafe or unsupported (m4p with DRM, wma, wav).

## Transaction and failure design

A SQLite transaction cannot include a filesystem rename or a tag rewrite, so real atomicity across the database and the disk is not available. The plan must say how the system gets the practical equivalent. Cover each of these with a concrete mechanism, not a statement of intent:

- **Atomicity.** A durable operation log with explicit states (for example planned, intent recorded, applied on disk, verified, committed), written before any disk change. Define startup recovery: for every operation not in a terminal state, how the tool inspects the disk and rolls forward or back. Every step must be safe to repeat.
- **Multi-file operations.** Renaming an artist may touch hundreds of files plus tags plus folders. Decide whether a batch is all-or-nothing with compensation or per-file with a resumable batch, what the user sees when file 212 of 300 fails, and how undo works for a whole batch and for one file.
- **Consistency.** State the invariants (one row per current path, no two files claiming one path, every row either matches the disk or is flagged) and where each is enforced: schema constraint, application check, or reconciliation scan.
- **Isolation.** One writer at a time. Decide how the web server, long-running jobs (scan, hash), and the CLI share the database and the library without interleaving. The UI will show stale data, so every mutation needs a precondition check that the file on disk still matches what the database believed (path, size, mtime, or a row version) and a defined response when it does not.
- **Durability.** Which writes are fsynced, the SQLite `synchronous` level for the operation log (the index currently uses `NORMAL`), and what a power cut on the Pi can leave behind given exFAT has no journal.
- **Tag writes.** mutagen rewrites a file in place and that is not atomic. Choose between writing to a temporary copy then renaming over, or saving the original tag bytes for restoration, and account for free space and for the hash and mtime changing.
- **Never overwrite, never delete.** `os.rename` silently replaces an existing destination on POSIX. Specify how a no-replace move is guaranteed. Cover exFAT specifics: case-insensitive names, case-only renames, illegal characters, Unicode normalization, moves staying on one device, creating destination folders, and what to do with folders left empty.
- **Drift.** Files change outside the tool. Define the reconciliation scan and how the UI presents rows that are missing, changed, or new.

For error handling, define an error taxonomy (invalid input, precondition failed, collision, unsupported format, I/O failure, library not mounted, out of space, permission, internal), how each maps to an API response and a UI message, what is logged, and which errors stop a batch. No error is swallowed.

## Web application

- Search GitHub and package registries before designing: check whether beets, an existing self-hosted tagger, or a library covers a meaningful part of this (tag writing, path templating, fingerprinting) and say what you will adopt, wrap, or decline, and why.
- Choose a server framework and a front-end approach suited to a Pi and a single maintainer, and justify them. State the cost of any build step.
- 100,000 rows means server-side paging, sorting, filtering, and search. Long operations run as background jobs with progress, cancellation, and a result the UI can revisit.
- Every mutation in the UI is a preview first (current to proposed, collisions, tag changes) and an explicit confirm second, matching the CLI's dry-run default.
- Security for a LAN service that can move files: bind address, whether authentication is needed, CSRF, validation of every input, and a guarantee that no request can read or write a path outside the configured library root.
- Deployment on the Pi: how the service starts and restarts, where the database and logs live relative to the library, and what `deploy_to_pi.sh` must change.

## How to work

1. Read `CLAUDE.md`, `docs/PLAN.md`, `docs/SPECS.md`, `docs/LIBRARY_SURVEY.md`, the source, and the tests. Run `ruff check . && ruff format --check . && pytest` and record the result. Run the `bd` commands above.
2. Write the plan to `docs/WEB_UI_PLAN.md`: scope and non-goals, the resolution of each conflict above, data model with schema and migration approach, the operation state machine and recovery procedure, API surface, UI screens, test strategy, and ordered phases.
3. Put every question only the owner can answer into one batch, each with your recommended answer, and ask once. Continue with everything that does not depend on the answers.
4. After the owner approves the plan, create the beads issues.
5. Finish with `bd lint`, `bd blocked`, and `bd ready`, and confirm that what shows as ready is exactly what you intend to be worked first.

Do not connect to the Pi, do not touch the real library, and do not commit or push in this session.

## Models

Implementation will be done by Qwen3.8 27, a smaller locally run model, not by you. Planning, design, and review are done by Claude models. Every step in the plan and every issue names the model that should do it, so the owner can route work without rereading the plan.

| Step | Recommended model | Why |
|------|-------------------|-----|
| This planning session: investigation, conflict resolution, data model, operation state machine, recovery design | Claude Fable 5.2 (`claude-fable-5-2`); Opus 5.5 if unavailable | The design decisions here are the ones that lose files if wrong |
| Writing the beads issues from the approved plan | Same session and model | The issue text is the implementer's whole context; it needs the design in its head |
| Phase 0 stabilisation issues | Qwen3.8 27 | Small, mechanical, checked by the quality gate |
| Implementation issues: pure logic, schema and repository code, API handlers, UI pages | Qwen3.8 27 | The default implementer |
| Implementation issues on the mutation path: operation log, recovery, no-replace move, tag writes, undo | Qwen3.8 27 implements, then a mandatory review issue | See below |
| Review of mutation-path code, security review of the web server, and the end of each phase | Claude Opus 5.5 (`claude-opus-5-5`) | Independent of the model that wrote the code |
| Routine review of non-mutating issues | Claude Sonnet 5.5 (`claude-sonnet-5-5`) | Cheaper, sufficient for pure logic and UI |
| Live verification on the Pi, and anything that touches the real library | Owner present, Claude Opus 5.5 driving | Not delegated to the implementation model |

Treat this table as the starting recommendation. Adjust it in the plan where you have a reason, and say what the reason is.

Because the implementer is a smaller model, write issues it can finish without design judgment:

- Name the exact files to create or change, the function and class signatures with types, and the test file and test names to write first.
- Give the exact commands that prove the issue is done and what their output should show.
- Quote the relevant decision from the plan in the issue rather than pointing at a section and expecting it to be read and interpreted.
- State what is out of scope and which existing functions must not change behaviour.
- Keep each issue to one module and its tests. If an issue needs a design choice to be made, the plan is not finished: make the choice here, or split out a design issue assigned to a Claude model.
- For every mutation-path implementation issue, create a paired review issue that depends on it and blocks whatever builds on it. The review issue lists what to check: every state transition has a crash test, no code path can overwrite or delete, preconditions are checked before any disk change.

Record the model on each issue as a label (`model:qwen3.8-27`, `model:opus-5.5`, `model:sonnet-5.5`, `model:fable-5.2`) and in the first line of the description, and give each phase in the plan a model column.

## Required shape of the phases

- **Phase 0, stabilise.** Get the current branch green and honest before anything is built on it: restore the deleted functions, fix or reopen `cvf`, finish or cut `2k2`/`z80`, bring `cli.py` under the limit, and correct stale docs. These are separate small issues.
- **Then a tracer bullet.** The thinnest slice through every layer: database with migrations and stable IDs, the operation log, one journaled rename of one file with recovery, one API endpoint, one page that lists files and renames one. Verified end to end on the Mac against a temp library, then on the Pi against a throwaway folder of copies, never the real library. Track it as its own issue, separate from the hardening that follows.
- **Then breadth**, in an order you justify: metadata editing with tag writes, pattern-based bulk rename and move, song hashing and the duplicates view, undo, reconciliation, deployment.

## Required shape of the issues

Be granular. One issue is one reviewable change that a fresh session can pick up cold and finish with the quality gate green, normally one module plus its tests and well under the 200-line file limit. If an issue needs the word "and" to describe what it delivers, split it.

Every issue has:

- a title that names the deliverable;
- a description giving why it exists and what is in and out of scope;
- design notes for any decision already made in the plan, with a pointer to the plan section;
- acceptance criteria that can be checked by running something, including the failure cases (for mutating code: the crash-at-each-step tests, the collision test, the precondition-failed test);
- the recommended model, as a `model:` label and in the first line of the description;
- type, priority, labels, a parent epic per phase, and dependencies added with `bd dep add` so that `bd ready` yields the correct order.

Tests come first in every implementation issue, per the repo's TDD rule. Mutating code is tested against temp directories with fault injection at each state transition; nothing is declared done on the basis of the happy path.

Reconcile the existing tracker rather than adding to it blindly. For every open or in-progress issue, and for `cvf`, state in the plan whether it is kept as is, rewritten, superseded (`bd supersede`), reopened, or closed, with the reason, and release the two expired leases. No new issue may duplicate an existing one.

## What to hand back

The path to the plan, the list of owner questions with your recommendations, the issue IDs grouped by phase with the dependency order and the model for each, the output of `bd ready`, and anything you could not verify along with where you looked.

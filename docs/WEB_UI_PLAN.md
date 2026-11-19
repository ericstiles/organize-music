# Web UI Plan: Music Library Manager on the Pi

Status: **Approved by owner 2026-11-17; ready for issue creation** · Written 2026-11-17 by Claude Opus 5.5 (planning fallback
for Fable 5.2) from [PLANNING_PROMPT.md](PLANNING_PROMPT.md).
Issue catalogue: [WEB_UI_ISSUES.md](WEB_UI_ISSUES.md). This plan supersedes the "Later: web UI"
row and decisions 4 and 5 of [PLAN.md](PLAN.md); the rest of PLAN.md still describes the
read-only CLI.

Sections marked **(Q-n)** were owner questions; §14 records every answer, all given 2026-11-17.

---

## 1. Verified starting state (2026-11-17, commit `2a9ee13`)

| Check | Result |
|-------|--------|
| `main` quality gate | green: `ruff check`, `ruff format --check`, 179 tests, 100% coverage |
| Branch `feat/phase2-naming-preview` | **red**: 23 ruff errors, 9 files need formatting, pytest fails at collection (3 modules) |
| `reports.py` | `057322a` replaced the `def render_metadata_report` line with the new preview renderer, leaving the old docstring and body as unreachable code after `return` |
| `cli.py` | 225 lines; `run_dupes` deleted but still referenced; `rename --apply` is a `TODO` |
| `rename` CLI | passes whole relative paths (`str(r.path)`) to `transform_name`, so it would rename **folders** too, contradicting `cvf`'s "filenames only" |
| `naming.py` | `render_name` never calls `sanitize`; duplicate `import re`; import after code; no length caps |
| `deploy_to_pi.sh` | `rsync -a --delete` into `~/organize_music/` without excluding `state/`; default index is `~/organize_music/state/index.db`, so **every deploy deletes the index on the Pi** unless the Pi's config overrides it (not checked: no Pi access this session) |
| Beads | `2k2`, `3d1` in progress with expired leases; `z80`, `dpf`, `cpc`, `8su`, `hpg`, `p1b` open; `cvf` closed but not done |

## 2. Scope and non-goals

**In scope:** web app on the Pi for one owner on the LAN; browse 100k files with server-side
paging, sorting, filtering, and search; rename and move by pattern or by hand; edit tag values on
one or many files with names and folders kept in agreement; duplicates grouped by audio-payload
hash; SQLite as the system of record with history; crash-safe journaled mutations with recovery
and undo; deployment as a service.

**Non-goals (v1):** playback or serving audio bytes; MusicBrainz or any online lookup; acoustic
fingerprinting (`hpg`, deferred); multi-user or remote internet access; TLS; editing fields beyond
the eight in `FIELD_NAMES`; cover-art editing; deleting anything in the library; tag writes for
formats other than mp3 and m4a (Q-4); moving non-art sidecars such as `.nfo`, `.txt`, and `.m3u`
(album art does move, §6.8).

## 3. Build, adopt, decline

Searched PyPI and GitHub on 2026-11-17.

| Candidate | Verdict | Reason |
|-----------|---------|--------|
| **beets 2.14** (CLI, own SQLite library, path templates, web plugin) | **Decline** as the engine | Its import flow assumes MusicBrainz matching and its own library schema. It has no crash-recovery log for moves, and adopting it means discarding the field-source model and the tested code. Borrow ideas only (template vocabulary, `$albumartist` fallback). |
| **mediafile 0.17** (beets' cross-format tag layer over mutagen) | **Adopt** for tag writes | Uniform field names across ID3 and MP4 atoms, years of use in beets, and it preserves frames it doesn't manage. Wrapped by one module, `tags/writer.py`. |
| Picard, onetagger, wrtag | Decline | Desktop apps, or tied to MusicBrainz or Go. None is a LAN web app over a local DB. |
| **FastAPI 0.163 + uvicorn 0.54 + Jinja2 3.1** | **Adopt** | Pydantic validates every input at the boundary, which suits a smaller implementer model. Sync handlers fit sqlite3. One process, one worker. aarch64 wheels exist. |
| **htmx 2.0.x** (one vendored JS file) | **Adopt** | Server-rendered pages with partial updates; **no build step**, no node on the Pi. Cost: one file committed under `web/static/` with its SHA-256 recorded. |
| SQLite FTS5 | Adopt | Search over path, artist, album, and title without another service. Availability on the Pi's Python is checked in the tracer (§15). |
| Chromaprint | Defer (`hpg`) | Not installed on the Pi; not needed for byte or payload duplicates. |

New runtime deps: `fastapi`, `uvicorn`, `jinja2`, `python-multipart`, `itsdangerous`, `mediafile`.
New dev dep: `httpx` (TestClient). Optional dev: `playwright` for one E2E smoke test, marked
`e2e` and skipped by default.

## 4. Conflict resolutions

### C1. Cache versus system of record
**Decision:** a new database, `library.db`, is the system of record; the old `index.db` stays a
cache used only by the legacy CLI commands until they are re-pointed (§12, Phase 8).
- Forward-only migrations: numbered SQL files in `db/migrations/NNNN_name.sql`, applied in order,
  version in `PRAGMA user_version`. Nothing ever drops a table on a version mismatch. A DB newer
  than the code refuses to open.
- Before any migration, the runner takes an online backup (`sqlite3.Connection.backup`) to
  `state/backups/library-v<old>-<UTC timestamp>.db`.
- Nightly backup (systemd timer), 14 kept, plus one copy on the SSD so a dead SD card doesn't
  take history with it.
- Every operation-state change is also appended to a JSONL mirror on the SSD
  (`work_dir/oplog/YYYY-MM.jsonl`, fsynced).
- **If the DB is lost or corrupt:** restore the latest backup, then replay the JSONL mirror for
  operations after the backup, then run reconciliation. If all backups are gone, a full scan
  rebuilds paths, tags, and hashes from disk, and the history comes back from the JSONL mirror
  keyed by path. **Permanently lost:** the `file_id`s (reassigned), drift events, and job history.

### C2. Identity
**Decision:** `files.file_id INTEGER PRIMARY KEY AUTOINCREMENT` is the stable identity and is
never reused. A rename updates `path` on the same row. **A song is not a table**: it is the set of
files sharing `audio_hash` (a `songs` view). Tags live in each file, so metadata belongs to the
file. "Edit every copy of this song" is a selection by `audio_hash`, not a separate entity to keep
in sync. The `hashes` table and `(root, path)` keys are retired in the new DB, which serves one
library root; the root is recorded in `settings`, and the DB refuses to open against a different
root.

### C3. What "song hash" means
**Decision:** `8su` becomes a **prerequisite**, rewritten as Phase 3.
- **Every** audio file is hashed: about 578 GB, roughly 30–60 minutes at USB 3 speeds; resumable
  and preemptible.
- `hash_kind='audio'` for mp3 and m4a: BLAKE2b-128 over the audio payload only. For mp3, skip the
  ID3v2 header and footer, a trailing ID3v1 `TAG` block, and an APEv2 tag. For m4a, hash the bytes
  of the top-level `mdat` atoms in file order.
- `hash_kind='file'` (whole file) for every other format. Groups never mix kinds.
- Validity stamp `(hash_size, hash_mtime_ns)`. When the stamp is stale, reconciliation re-hashes.
- **After the tool's own tag write**, the retag step hashes the new temp copy and **requires** the
  audio hash to equal the old one before swapping. This is both the corruption check and the
  reason no re-hash is needed afterwards; the commit writes the new stamp with the old hash.

### C4. Who may modify files
**Decision:** one mutation path. Every change to the library is an `operation` in a `batch`,
executed only by the server's single job worker, which holds the process-wide writer lock (§6.4).
- CLI mutation commands are dropped (Q-5). The CLI keeps the read-only commands plus `serve`,
  `recover`, `db migrate`, `db backup`, and `set-password`.
- `cvf` (`rename`): reopen (closed with a `TODO` in place of the apply step), remove `rename.py`
  and the subcommand in Phase 0, then supersede with the pattern-rename issue. The pattern
  `${dir}/${stem}.${ext}` with sanitising is exactly "tidy filenames in place".
- `dpf` (`organize`): superseded by the Phase 4 pattern rename-and-move epic.
- `cpc` (`quarantine`): kept, rewritten as Phase 9: a batch of `move` operations whose destination
  root is the quarantine folder (an allowed second root on the same device).

### C5. Collision policy (Q-1, owner decided 2026-11-17)
**Decision:** never overwrite and never need a human mid-batch. A colliding file gets a
**rule-based `-copy-N` suffix**, shown in the preview before anything moves.
- **Taken** means a file already exists at the target on disk, in the DB, or as another file's
  target in the same batch. Names are compared case-insensitively after NFC.
- **Who keeps the plain name:**
  1. a file already at the target keeps it;
  2. otherwise, among incoming files, the highest bitrate keeps it;
  3. ties go to the file with the lowest `file_id`.
- **The others** get `-copy-N` before the extension, for example
  `01-Learn_To_Fly-copy-1.mp3`. N is the lowest integer from 1 up that is free on disk, in the
  DB, and in the batch.
- **Applies to identical audio too.** Files with the same audio hash get the suffix like any other.
  They still group together on the Duplicates page, so a later quarantine (`cpc`) can remove the
  extra copies. This keeps reorganising fully automatic, and no source folder is left half-emptied.
- **When N is fixed:** at preview time, stored in the operation's `dst`. If that name is taken by
  the time the move runs (an external change), the unit fails with `PRECONDITION_FAILED` and
  "Retry failed" re-previews it with a new N.
- **Manual override:** the owner can still type any target by hand in the preview.
- This keeps the spirit of `3z4`'s `-copy-N` and replaces PLAN.md's "leave colliding files in
  place".

### C6. Template vocabulary (Q-2, owner decided 2026-11-17)
**Decision:** default `${artist}/${album}/${track}-${title}.${ext}`. The track number leads the
filename so files sort in album order.

**Number-prefix rules** (disc option A; owner agreed 2026-11-17). `${track}`
renders the whole number prefix:

| # | Rule |
|---|------|
| N1 | The track number is **always at least 2 digits** (`01`); 3 when the track number or the album's track total is ≥ 100 (`001`). |
| N2 | **No track number:** no prefix at all, and no disc number either. The `-` after the placeholder goes too: `Bonus.mp3`. A bare disc number is never written. |
| N3 | **Multi-disc album:** the album's disc total is > 1 (from a tag such as `1/2`), **or** any present file with the same album artist (artist when empty) and album has disc ≥ 2. The planner gets this set of album keys from the DB, so disc 1 is prefixed even when its own tags carry no total. |
| N4 | **On a multi-disc album with a track number:** `<disc>-<track>`, e.g. `1-01-Intro.mp3`, `2-01-Bonus.mp3`. The disc is unpadded; 2 digits when the disc total is ≥ 10 (`01-01`). |
| N5 | **Single-disc album, or disc missing or 0:** the track number only, `01-Intro.mp3`. |

What the rules guarantee:
- A prefix is either `TT-` or `D-TT-`. The track part is always 2+ digits, so a single digit before
  the first `-` is never a track number.
- A disc with one song still shows its track: `2-01-Bonus.mp3`. The confusing `1-Intro.mp3`
  (disc 1, no track) can't be produced, because of N2.
- Disc 1 sorts before disc 2: `1-…` < `2-…`, with every disc on the same width.
- The tool never reads its own filenames back for meaning; tags are the source of truth (C7). A
  title that happens to start with digits (`1-800-273-8255` with no track number) is only a cosmetic
  look-alike.

| Placeholder | Value |
|-------------|-------|
| `${artist}` `${album_artist}` `${album}` `${title}` `${genre}` | field value, sanitised |
| `${track}` | the number prefix per rules N1–N5; empty if no track number |
| `${disc}` | disc number, unpadded; empty if missing or 0 (for custom patterns only) |
| `${year}` | 4 digits; empty if missing |
| `${ext}` | current extension, lower-case |
| `${dir}` | current folder (relative), for in-place renames |
| `${stem}` | current filename without extension, for in-place renames |

- `${albumartist}` falls back to `${artist}`.
- A missing artist or album becomes `Unknown_Artist` or `Unknown_Album`, so files never collapse
  into the library root. This changes naming rule 4 in PLAN.md.
- An empty placeholder takes its adjacent `-` or `_` separator with it.
- Each segment is sanitised (PLAN.md rules 1–3), NFC-normalised, and capped at 120 characters
  (the extension is preserved). The whole relative path is capped at 400 characters.
- An unknown placeholder is a validation error, not an empty string.
- `${track #}` from `3z4` is retired; `${track}` is the number.

### C7. Metadata edits versus field sources (Q-4, owner decided 2026-11-17)
**Where metadata lives:** tags (artist, album, title, track, and the rest) are stored **inside each
audio file**: ID3 frames in an mp3, atoms in an m4a. They are not stored in the filename. The
database holds a **copy** of every file's tags so 100k files can be searched and sorted quickly,
plus the history of every change. The file is the source of truth for tag values; the database is
the source of truth for paths, identity, and history.

**Decision:** a user edit is a **tag write into the file**, followed by a database update, so the
two always agree. There are no database-only overrides.
- After a successful write and re-read, the field's source is `tag`. The history row records that
  the change came from the owner, with before and after values.
- Writes are supported for **mp3 and m4a only**. m4p (DRM), wma, wav, ogg, and every other format
  show as `unsupported` in the preview and are skipped: their tags can't be edited through the tool
  (about 160 files per the 2026-11-03 survey). They can still be renamed and moved.
- ID3: keep the file's existing ID3 version. Files with no ID3v2 tag get v2.3, for iTunes and iPod
  compatibility. Existing ID3v1 blocks are updated, never added.

## 5. Data model (migration `0001_initial.sql`)

```sql
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);  -- library_root, created_at

CREATE TABLE files (
  file_id        INTEGER PRIMARY KEY AUTOINCREMENT,
  path           TEXT,            -- relative to library root, exactly as on disk; NULL iff gone
  path_key       TEXT,            -- NFC(path).casefold(); exFAT collision key; NULL iff gone
  last_path      TEXT NOT NULL,   -- kept after the file is gone
  status         TEXT NOT NULL CHECK (status IN ('present','missing','changed','gone')),
  kind           TEXT NOT NULL CHECK (kind IN ('audio','art')),  -- art: jpg jpeg png gif bmp webp
  size           INTEGER NOT NULL,
  mtime_ns       INTEGER NOT NULL,
  ext            TEXT NOT NULL,
  raw_tags       TEXT, read_error TEXT, duration_seconds REAL, bitrate_kbps INTEGER,
  artist, artist_src TEXT NOT NULL, album_artist, album_artist_src TEXT NOT NULL,
  album, album_src TEXT NOT NULL, title, title_src TEXT NOT NULL,
  track_number, track_number_src TEXT NOT NULL, disc_number, disc_number_src TEXT NOT NULL,
  year, year_src TEXT NOT NULL, genre, genre_src TEXT NOT NULL,
  audio_hash     TEXT,
  hash_kind      TEXT CHECK (hash_kind IN ('audio','file')),
  hash_size      INTEGER, hash_mtime_ns INTEGER,
  row_version    INTEGER NOT NULL DEFAULT 1,
  first_seen_at  TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK ((status = 'gone') = (path IS NULL)),
  CHECK ((path IS NULL) = (path_key IS NULL)),
  CHECK ((audio_hash IS NULL) = (hash_kind IS NULL))
);
CREATE UNIQUE INDEX files_path_key ON files(path_key) WHERE path_key IS NOT NULL;
CREATE INDEX files_hash ON files(hash_kind, audio_hash) WHERE audio_hash IS NOT NULL;
CREATE INDEX files_status ON files(status);
CREATE INDEX files_folder ON files(kind, path) WHERE path IS NOT NULL;  -- "audio left in folder?"
CREATE INDEX files_artist ON files(artist COLLATE NOCASE);
CREATE INDEX files_album  ON files(album  COLLATE NOCASE);
CREATE INDEX files_title  ON files(title  COLLATE NOCASE);
CREATE VIEW songs AS
  SELECT hash_kind, audio_hash, COUNT(*) AS copies, SUM(size) AS total_size
  FROM files WHERE kind = 'audio' AND status <> 'gone' AND audio_hash IS NOT NULL
  GROUP BY hash_kind, audio_hash;

CREATE VIRTUAL TABLE files_fts USING fts5(
  path, artist, album, title, content='files', content_rowid='file_id',
  tokenize='unicode61 remove_diacritics 2');
-- plus AFTER INSERT/UPDATE/DELETE triggers on files keeping files_fts in sync

CREATE TABLE batches (
  batch_id     INTEGER PRIMARY KEY AUTOINCREMENT,
  kind         TEXT NOT NULL CHECK (kind IN ('rename','edit','undo','quarantine')),
  state        TEXT NOT NULL CHECK (state IN ('draft','confirmed','running','completed',
                 'completed_with_errors','stopped','cancelled','discarded')),
  description  TEXT NOT NULL,
  request_json TEXT NOT NULL,     -- the validated request that produced the preview
  undo_of      INTEGER REFERENCES batches(batch_id),
  total INTEGER NOT NULL DEFAULT 0, succeeded INTEGER NOT NULL DEFAULT 0,
  failed INTEGER NOT NULL DEFAULT 0, skipped INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, confirmed_at TEXT, finished_at TEXT
);

CREATE TABLE operations (
  op_id         INTEGER PRIMARY KEY AUTOINCREMENT,
  batch_id      INTEGER NOT NULL REFERENCES batches(batch_id),
  file_id       INTEGER NOT NULL REFERENCES files(file_id),
  unit_seq      INTEGER NOT NULL,   -- one unit = all steps for one file
  step_seq      INTEGER NOT NULL,   -- retag before move within a unit
  kind          TEXT NOT NULL CHECK (kind IN ('move','retag')),
  state         TEXT NOT NULL CHECK (state IN ('planned','intent','staged','parked','applied',
                  'committed','failed','skipped','needs_attention')),
  expect_path TEXT NOT NULL, expect_size INTEGER NOT NULL,
  expect_mtime_ns INTEGER NOT NULL, expect_row_version INTEGER NOT NULL,
  params_json   TEXT NOT NULL,      -- per kind, §6.2 / §6.3
  result_json   TEXT,
  error_code    TEXT, error_detail TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE (batch_id, unit_seq, step_seq)
);
CREATE UNIQUE INDEX operations_one_active_per_file ON operations(file_id)
  WHERE state IN ('intent','staged','parked','applied');
CREATE INDEX operations_file ON operations(file_id, op_id);

CREATE TABLE events (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id  INTEGER NOT NULL REFERENCES files(file_id),
  kind     TEXT NOT NULL CHECK (kind IN ('discovered','changed','missing','returned',
             'moved_externally','forgotten','rehashed')),
  detail_json TEXT NOT NULL, at TEXT NOT NULL
);

CREATE TABLE jobs (
  job_id   INTEGER PRIMARY KEY AUTOINCREMENT,
  kind     TEXT NOT NULL CHECK (kind IN ('scan','hash','batch','recover')),
  state    TEXT NOT NULL CHECK (state IN ('queued','running','paused','succeeded','failed',
             'cancelled','interrupted')),
  batch_id INTEGER REFERENCES batches(batch_id),
  progress_done INTEGER NOT NULL DEFAULT 0, progress_total INTEGER,
  cancel_requested INTEGER NOT NULL DEFAULT 0,
  result_json TEXT, error_code TEXT, error_detail TEXT,
  created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT
);
```

**History** of a file is its committed and failed `operations` plus its `events`, ordered by
time. There is no separate history table to drift out of sync.

## 6. Mutation engine

### 6.1 Rules every step follows
- **`state` is the last completed durable step.** A step is: (1) do the disk action, (2) fsync the
  file or directories it touched, (3) write the new state in a DB transaction with
  `synchronous=FULL`, (4) append the transition to the JSONL mirror. A crash anywhere leaves either
  the old state with the disk action done or not done, or the new state. Recovery tells which by
  inspecting the disk.
- Every disk action can be detected afterwards by exact-name checks, so every step can be repeated.
- **`entry_exists(parent, name)` compares exact names from `os.listdir`**, never `Path.exists`:
  on case-insensitive exFAT, `exists("a.mp3")` is true when `A.mp3` is present.
- **No call that can replace or delete a library file exists in the code.** The only primitives
  are `rename_noreplace`, `mkdir_one`, `rmdir_if_empty`, `copy_new` (`O_EXCL`), and
  `discard_temp`, which unlinks only files under `work_dir/tmp/` named `op-<id>.*` and raises
  for any other path. A test greps `src/` for `os.rename`, `os.replace`, `Path.rename`,
  `Path.replace`, `os.remove`, `os.unlink`, `Path.unlink`, `shutil.move`, `shutil.rmtree` outside
  `fsops/` and fails if it finds any.
- Every operation stores its precondition `(expect_path, expect_size, expect_mtime_ns,
  expect_row_version)`. Before the move to `intent`, the engine re-stats the disk and re-reads the
  row. Any mismatch fails that operation with `PRECONDITION_FAILED`, marks the row `changed`, and
  continues with the next unit.
- `SimulatedCrash` (tests only) subclasses `BaseException`, so no `except Exception` in the engine
  can swallow it.

### 6.2 Move operation
`params_json`: `{src, dst, via, created_dirs, dst_root}`. `via` is the intermediate name for
case-only renames (`work_dir`-free: `<parent>/.om-<op_id>.tmp`). `created_dirs` lists the folders
created, parent first. `dst_root` is `library` or `quarantine`.

| From | Step | To |
|------|------|----|
| planned | precondition check; validate `dst` (§9.4); dst free (DB `path_key` and `entry_exists`); same device; record folders to create | intent |
| intent | `mkdir_one` each missing folder; `rename_noreplace(src, dst)` (or `src→via` for case-only); fsync both parents | applied (or staged for case-only) |
| staged | `rename_noreplace(via, dst)`; fsync parent | applied |
| applied | stat `dst` equals expected size and mtime; DB: `path`, `path_key`, `row_version+1`, op `committed` in one transaction | committed |
| committed | `rmdir_if_empty` on each emptied source folder up to the library root (best effort, logged) | (terminal) |

**Recovery** for a move in `intent`, `staged`, or `applied`; S, V, D = an entry exists at src,
via, dst:

| S | V | D | Meaning | Action |
|---|---|---|---------|--------|
| ✓ | ✗ | ✗ | rename never happened | `rmdir_if_empty` the `created_dirs` in reverse; op `failed` (`INTERRUPTED`) |
| ✗ | ✓ | ✗ | case-only, half done | `rename_noreplace(via, dst)`, then the applied path |
| ✗ | ✗ | ✓ (size and mtime match) | rename done | verify, then commit |
| ✗ | ✗ | ✓ (mismatch) | something else is at dst | `needs_attention` |
| ✓ | any | ✓ | both names exist | `needs_attention`. **Never remove either**: an exFAT power cut between writing the new directory entry and clearing the old one leaves two entries sharing one cluster chain; deleting one frees the other's data. The UI tells the owner to run `fsck.exfat`. |
| ✗ | ✗ | ✗ | file not found | `needs_attention` |

### 6.3 Retag operation (copy, tag, park, swap)
`params_json`: `{path, tmp, parked, parked_dirs, before, after, expect_audio_hash, tmp_size,
tmp_mtime_ns}`.
- `tmp` is `work_dir/tmp/op-<id>.<ext>`.
- `parked` is the original's place in the **purge folder** (§6.9): `purge_dir/<path>`, the same
  relative path the file had in the library at the time of the edit, with `-copy-N` (C5) if a
  file is already there. It is fixed at preview time.
- `parked_dirs` lists the purge sub-folders created for it.
- `work_dir` and `purge_dir` are on the same device as the library and outside it (validated at
  startup).

| From | Step | To |
|------|------|----|
| planned | precondition check; free space ≥ file size + 256 MiB reserve | intent |
| intent | `copy_new(path, tmp)`; fsync; write `after` with `tags/writer`; re-read: fields equal `after`; audio hash of `tmp` equals `expect_audio_hash`; record tmp size and mtime | staged |
| staged | `mkdir_one` each missing purge sub-folder; `rename_noreplace(path, parked)`; fsync both dirs | parked |
| parked | `rename_noreplace(tmp, path)`; fsync dir | applied |
| applied | stat `path` equals the tmp size and mtime; re-read tags; DB: size, mtime, raw tags, fields (source `tag`), hash stamp (same hash), `row_version+1`, op `committed` | committed |

**Recovery:** P, T, K = entry at path, tmp, parked:

| State | Disk | Action |
|-------|------|--------|
| intent or staged | P matches precondition, K ✗ | `discard_temp(tmp)` if T; op `failed` (`INTERRUPTED`), retryable |
| intent or staged | P mismatch | `needs_attention` |
| staged or parked | P ✗, K ✓, T ✓ (tmp size and mtime match) | `rename_noreplace(tmp, path)`, then the applied path |
| parked | P ✗, K ✓, T ✗ | roll back: `rename_noreplace(parked, path)`; op `failed` |
| parked or applied | P ✓ (matches tmp), K ✓ | commit |
| any other combination | | `needs_attention` |

Originals in the purge folder stay until the owner deletes them by hand (§6.9); they give
byte-exact restore and a
safety net on top of undo.

### 6.4 Batches, units, and isolation
- **Preview then confirm.** A preview computes the planned units, each carrying its precondition,
  and stores them as a draft in `state_dir/drafts.db`, a scratch database owned by the web
  process. Drafts and selection snapshots never go into `library.db`, which keeps exactly one
  writer (revised 2026-11-17 while writing the Phase 4 issues). Confirm enqueues a `batch` job with
  the draft id. The job first re-checks every `expect_row_version` against `library.db`. If any
  differs, the job fails with `PREVIEW_STALE`, nothing is written, and the UI offers to re-preview.
  Otherwise it writes the batch and its `planned` operations in one transaction and runs them.
- **Units.** All operations for one file form a unit (retag before move). All preconditions,
  collision checks, and space checks for a unit run before its first disk change. A unit that
  fails before its first change is `failed` with nothing touched. If a unit's retag commits and its
  move then fails with an I/O error, the file is consistent (DB matches disk) but not at its
  target; the batch result shows it as `partial` with a retry action. No cross-file compensation.
- **Per-file, resumable batches.** When file 212 of 300 fails with a per-file error, that unit is
  recorded and the batch continues. The result page lists every unit with its outcome; "Retry
  failed" makes a new draft from the failed units.
- **Errors that stop the batch:** `LIBRARY_NOT_MOUNTED`, `OUT_OF_SPACE`, `IO_ERROR`, `INTERNAL`,
  and three consecutive `PERMISSION`. Remaining operations become `skipped`, the batch `stopped`.
- **Cancel** takes effect between units: the remaining operations are `skipped` and the batch is
  `cancelled`.
- **One writer.** The server process takes an exclusive `fcntl.flock` on `state/writer.lock` at
  startup and holds it for its lifetime. CLI commands that write `library.db` (`recover`,
  `db migrate`) take the same lock and fail with "server is running" if they can't get it.
  Inside the server, one job worker thread owns the only write connection. HTTP handlers open
  `query_only` read connections (WAL lets them read concurrently) and only enqueue jobs.
- **Preemption.** Scan and hash jobs check between files whether a batch job is queued. If so, they
  checkpoint, return to `paused`, and re-queue behind it. Both are resumable from DB state, so an
  edit never waits for a 40-minute hash.
- **Startup.** Acquire the lock, run migrations, check that the library is mounted (§6.5), then run
  `recover` over every operation in `intent`, `staged`, `parked`, or `applied` **before** the
  worker accepts jobs. Jobs left `running` become `interrupted`. If the library isn't mounted, the
  server starts read-only, and every mutation and recovery waits with `LIBRARY_NOT_MOUNTED`.

### 6.5 Durability
- Writer connection: `journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`. Readers:
  `query_only=ON`. Scan and hash commit every 200 files (operation-log rows commit per step).
- Files: `fsync` on `copy_new` output and after tag writes; `fsync_dir` on both parents after
  every rename and `mkdir_one`. The JSONL mirror is fsynced per line.
- **Where things live:** `library.db` and backups on the Pi's own storage
  (`~/.local/share/organize_music/`), never on the exFAT SSD (no journal; SQLite locking on exFAT
  is not worth trusting). `purge_dir` on the SSD outside the library:
  `$MUSIC_LIB/../purge` (§6.9). `work_dir` (tmp, oplog mirror)
  on the SSD outside the library:
  `$MUSIC_LIB/../_organize_music_work`.
- **Mounted check:** config names `library_mount`; `os.path.ismount(library_mount)`, the library
  root exists, and `st_dev` of the root, `work_dir`, and quarantine are equal.
- **Power cut on exFAT** can leave: a rename not persisted (recovery sees "not applied"); a doubled
  directory entry (§6.2, `needs_attention`, never auto-fixed); a partial temp copy (never trusted:
  verified or discarded); a corrupt FAT chain. After any unclean shutdown, the server's banner
  recommends `sudo fsck.exfat -n /dev/sda1` (owner runs it). The tool never runs fsck itself.

### 6.6 exFAT specifics
| Concern | Mechanism |
|---------|-----------|
| No-replace rename | Linux: `renameat2(AT_FDCWD, src, AT_FDCWD, dst, RENAME_NOREPLACE)` via ctypes (glibc ≥ 2.28). macOS (dev/tests): `renamex_np(src, dst, RENAME_EXCL)`. No fallback: `EINVAL` or `ENOSYS` raises `UnsupportedPlatform` and nothing moves. Verified on the Pi's exFAT in the tracer (§15). |
| Case-insensitive names | `path_key` unique index; `entry_exists` by exact name |
| Case-only rename | two no-replace renames via `.om-<op_id>.tmp` in the same folder |
| Illegal characters | sanitiser (PLAN.md rules 1–3) on every proposed segment; hand-typed names are validated, not silently changed (422 shows the cleaned form) |
| Unicode | new names written NFC; existing names kept as found; comparisons on NFC + casefold |
| Same device | `st_dev` check of source parent and destination parent before `intent` |
| Destination folders | `mkdir_one` per missing component, recorded in `created_dirs` |
| Emptied folders | `rmdir_if_empty` after commit: only `os.rmdir`, which fails on any entry. Art follows its audio (§6.8); folders still holding `.nfo`, `.txt`, or `.m3u` stay and are listed in the batch result. |
| Length | segment ≤ 120 characters, relative path ≤ 400 |

### 6.7 Undo
- **Undo a batch:** build an `undo` draft from its committed operations in reverse order. A move
  becomes a move back; a retag becomes a retag to the `before` values. Each inverse operation's
  precondition is the original's post-state. A file changed since then fails its unit with
  `PRECONDITION_FAILED` ("undo the later batch first"); the others proceed. The draft is previewed
  and confirmed like any batch.
- **Undo one file:** the same, filtered to that file's units.
- An undo is itself a batch and can be undone.
- Undo of a tag edit writes the old values back; it does **not** need the original in the purge
  folder, so undo still works after the owner empties the purge folder. Byte-exact restore from
  the purge folder is a separate later action, not undo.

### 6.8 Album art follows its audio (Q-7, owner decided 2026-11-17)
Art files (`kind='art'`) are indexed by the scan (stat and a whole-file hash; no tags) and moved
by the same `move` operation as audio. `ops/plan_art.py` (pure) adds art units to a rename or
move batch:
- **When:** art in folder F moves only if the batch leaves **no audio** in F. Audio outside the
  batch still counts. Art "follows the last audio out", so art never strands an album still using
  it.
- **Where:** to the destination folder that receives the most of F's audio in this batch; ties go
  to the first path in sort order. The art keeps its filename, sanitised.
- **Never at the root:** art directly in the library root, a folder with no owner, never moves.
- **Collision at the destination:**
  - byte-identical art already there: the incoming copy moves to the **purge folder** at its
    original relative path (§6.9), never deleted;
  - different art: `-copy-N`, as in C5.
- **Ordering:** art units run after every audio unit from F has committed. If any of those audio
  units failed, the art unit is `skipped`, because F still has audio.
- Art is excluded from Duplicates, search, and tag editing. Undo moves art back like any move.

### 6.9 Purge folder (Q-6, owner decided 2026-11-17)
The tool never deletes a library file. Anything it replaces goes to the purge folder, and **the
owner empties it by hand** whenever they choose. The tool has no purge command.
- **Location:** config `purge_dir`, default
  `$MUSIC_LIB/../purge`. It is on the same SSD as the library (so
  moving a file there is an instant rename and uses no extra space) and outside the library root.
  Startup validates both.
- **Layout:** a file keeps the **same folder structure it had in the library** at the moment it was
  replaced. Example: editing the artist of `Carbon Leaf/Echo Echo/01 Learn To Fly.mp3` puts the
  original at `purge/Carbon Leaf/Echo Echo/01 Learn To Fly.mp3`.
- If the same file is edited again later, the next original gets `-copy-N` (C5), so nothing in the
  purge folder is ever overwritten.
- **What goes there:** the original of every tag edit (§6.3), and incoming album art identical to
  art already at the destination (§6.8).
- **Space:** the originals use as much space as the files edited (300 songs ≈ 2–3 GB). The banner
  shows the purge folder's total size, from the DB, so the owner knows when to empty it.
- **After the owner deletes from the purge folder:** undo still works (it writes the old tag values
  back); only byte-exact restore of those originals is gone. The DB records each purged original's
  path, and the UI marks it "not found" once it's gone; nothing breaks.
- The purge folder is never scanned as part of the library, and the tool never reads it except to
  check that a parked original exists.

### 6.10 Invariants and where they are enforced
| # | Invariant | Enforced by |
|---|-----------|-------------|
| I1 | One row per current path, case-insensitively | schema: partial unique index on `path_key` |
| I2 | No two files at one path on disk | fs: `RENAME_NOREPLACE`, `copy_new` with `O_EXCL` |
| I3 | At most one in-flight operation per file | schema: `operations_one_active_per_file` |
| I4 | Every `present` row matches the disk, or is flagged | precondition checks (app) and the reconciliation scan |
| I5 | No operation stays non-terminal at rest | startup recovery (app); `CHECK` on state values |
| I6 | Every mutated path is inside the library or quarantine root | `paths.resolve_target` (app), the only path constructor the engine accepts |
| I7 | Library files are never replaced or deleted | fsops primitives only (app) and the source-grep test |
| I8 | One writer | `flock` (OS) and the single worker thread (app) |
| I9 | Audio is never changed by a tag write | audio-hash equality check before swap (app) |

## 7. Reconciliation (drift)
`scan/reconcile.py` (pure) compares a stat-only walk against DB rows and returns actions; the
`scan` job applies them:
- same `path_key`, same size and mtime: no-op;
- same `path_key`, changed: status `changed`, re-read tags, re-hash, `row_version+1`, event `changed`;
- DB row with no file: status `missing`, event `missing` (never removed automatically);
- file with no row: if it matches **exactly one** `missing` row by size and then audio hash, update
  that row's path (event `moved_externally`); otherwise insert a row (event `discovered`). Audio
  extensions get `kind='audio'`, art extensions `kind='art'`; other files are not indexed;
- `missing` row whose path reappears with the same size: `present`, event `returned`.

The UI's Drift page lists missing, changed, and new files. Actions: rescan selected; "forget" a
missing row (status `gone`; history kept). Operations are refused on files that aren't `present`.

## 8. Errors

| Code | Meaning | HTTP | Stops batch | UI message |
|------|---------|------|-------------|------------|
| `INVALID_INPUT` | request fails validation | 422 | n/a | field-level message |
| `PREVIEW_STALE` | rows changed since preview | 409 | n/a | "Files changed since preview. Re-preview?" |
| `PRECONDITION_FAILED` | disk or row differs from expectation | 409 (unit) | no | "Changed on disk; rescan" |
| `COLLISION` | target taken | 409 (unit) | no | "Target exists: …" |
| `UNSUPPORTED_FORMAT` | tag write not allowed for format | 415 (unit) | no | "Can't edit tags in .wma" |
| `IO_ERROR` | `OSError` other than below | 500 | **yes** | "Disk error; batch stopped" |
| `LIBRARY_NOT_MOUNTED` | mount check fails | 503 | **yes** | banner |
| `OUT_OF_SPACE` | below reserve, or `ENOSPC` | 507 | **yes** | "Not enough free space" |
| `PERMISSION` | `EACCES` or `EPERM` | 500 (unit) | after 3 in a row | "Permission denied" |
| `NEEDS_ATTENTION` | recovery found ambiguous disk state | 409 | n/a | Recovery page |
| `UNSUPPORTED_PLATFORM` | no-replace rename unavailable | 500 | **yes** | startup refuses mutations |
| `INTERNAL` | anything else | 500 | **yes** | "Internal error #<id>" |

- One `AppError(code, message, detail)` hierarchy lives in `errors.py`. `fsops` maps `errno` to
  codes in one function.
- API responses use the envelope `{"ok": bool, "data": …, "error": {"code", "message"}}`. HTML
  routes render the same message in a flash region.
- **Logging:** every error is logged as structured JSON with the code, op, batch, file id, and
  traceback for `INTERNAL` and `IO_ERROR`. Log lines carry file ids, not full paths; paths are in
  the DB.
- A test asserts that no `except` clause in `src/` has a body of just `pass`.

## 9. Web application

### 9.1 Stack and process
FastAPI app factory `web.app.create_app(config) -> FastAPI`, Jinja2 templates with autoescape on,
htmx vendored, one CSS file. Run with `organize-music serve` (uvicorn, **1 worker**). No build
step.

### 9.2 API surface (HTML pages and htmx partials; JSON where noted)
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/healthz` | JSON: DB ok, library mounted, pending recovery count (no auth) |
| GET/POST | `/login`, POST `/logout` | session auth (Q-3) |
| GET | `/` `/files` | library table: `page`, `size` (≤ 200), `sort` (whitelist), `dir`, `q` (FTS), `status`, `ext`, `missing_field`, `folder` prefix |
| GET | `/files/{file_id}` | detail: fields with sources, raw tags, history |
| POST | `/selections` | resolve a selection (ids, or "all matching filter") to a server-side snapshot id |
| POST | `/batches/rename/preview` | pattern or per-file manual targets → draft batch |
| POST | `/batches/edit/preview` | field, value, re-path flag → draft batch |
| GET | `/batches/{id}` | preview or result table, paged |
| POST | `/batches/{id}/confirm` | → 202 with job id, or 409 `PREVIEW_STALE` |
| POST | `/batches/{id}/discard` | draft → discarded |
| POST | `/batches/{id}/undo/preview`, `/files/{id}/undo/preview` | undo draft |
| GET | `/jobs`, `/jobs/{id}` | progress (htmx polls every 2 s) |
| POST | `/jobs/{id}/cancel`, `/jobs/scan`, `/jobs/hash` | job control |
| GET | `/dupes` | groups by `(hash_kind, audio_hash)`, sort by reclaimable bytes, paged |
| GET | `/drift` POST `/drift/forget` | reconciliation view |
| GET | `/recovery` | operations in `needs_attention`, with disk observations |

### 9.3 Screens
1. **Library:** filter bar, paged table, row checkboxes, "select all N matching", actions menu
   (Rename by pattern, Edit field).
2. **File detail:** fields with source badges, raw tags, history timeline, undo per committed unit.
3. **Rename by pattern:** pattern input with vocabulary help → preview (current → proposed;
   badges `ok`, `unchanged`, `renamed_copy` (got `-copy-N`, C5), `invalid`); per-row manual override;
   counts; Confirm.
4. **Edit field:** field picker, new value, "also re-apply pattern" (Q-8) → preview of tag and
   path changes → Confirm.
5. **Batch result and history:** per-unit outcome, retry failed, undo.
6. **Jobs:** progress bars, cancel.
7. **Duplicates:** groups with copies, paths, size, reclaimable total.
8. **Drift**, 9. **Recovery**, 10. **Login**.
A persistent banner shows library-not-mounted, mutations disabled, or recovery needed.

### 9.4 Security
- **Bind:** config `bind_host`, default `127.0.0.1`. The owner sets the Pi's LAN address
  explicitly. Never `0.0.0.0` by default.
- **Auth (Q-3):** one password, scrypt hash in `state/auth.json` (mode 0600), set by
  `organize-music set-password`. Signed session cookie via Starlette `SessionMiddleware`: secret in
  `state/secret.key` (0600), `HttpOnly`, `SameSite=Strict`, 12 h max age. Five failed logins a
  minute lock login for a minute. Plain HTTP on the LAN means the password can be sniffed there;
  TLS is a non-goal and the owner accepts that by answering Q-3.
- **CSRF:** per-session token required in the `X-CSRF-Token` header (htmx `hx-headers`) or a form
  field on every non-GET; `Origin`, when present, must match. GET handlers never mutate.
- **Host header allowlist** (`bind_host`, `localhost`, configured names) against DNS rebinding.
- **Input validation:** Pydantic models with length limits (value ≤ 255, pattern ≤ 400), no
  control characters, sort and filter enums whitelisted, ids are positive ints.
- **Paths:** requests carry file ids, never filesystem paths. Hand-typed targets and pattern output
  go through `paths.resolve_target(root, rel)`, which rejects absolute paths, `..`, empty segments,
  and NUL. It joins under the root, walks each existing component with `lstat`, rejects symlinks,
  and checks that `realpath` is inside the root. No route serves file bytes.
- XSS: autoescape on; tag values are untrusted text.
- **Mutations off by default:** config `mutations_enabled: false` until the owner turns it on (§12
  gate). With it off, preview works and confirm returns 403 `MUTATIONS_DISABLED`.

### 9.5 Paging and search at 100k rows
`LIMIT/OFFSET` over indexed columns with a deterministic tiebreak on `file_id`; `COUNT(*)` cached
per filter for 30 s. FTS5 `MATCH` for `q` with user input escaped as a phrase. A selection snapshot
stores `file_id`s in a temp table keyed by snapshot id, so "all 3,214 matching" is fixed at preview
time.

## 10. Deployment on the Pi
- **Service:** systemd **user** unit `organize-music.service` (`loginctl enable-linger`, no root),
  `ExecStart=.venv/bin/organize-music serve`, `Restart=on-failure`, `RestartSec=5`. The library
  mount is checked by the app at startup, not by systemd, because the external drive is a desktop
  automount that may appear late (Q-9: app waits; an fstab mount is optional and owner-run).
- **Paths:** state `~/.local/share/organize_music/` (`library.db`, `backups/`, `auth.json`,
  `secret.key`, `writer.lock`); logs `~/.local/state/organize_music/logs/` (rotating, plus journald);
  config `~/.config/organize_music/config.yaml`; work dir on the SSD (§6.5). None is under the
  rsync target.
- **`deploy_to_pi.sh` changes:**
  1. Add `--exclude 'state/'` immediately (Phase 0); the config default moves to `~/.local/share`.
  2. Install or refresh the user unit.
  3. Run `organize-music db migrate --check`, then back up, then migrate, **while the service is
     stopped**.
  4. Restart the service.
  5. `curl -fsS http://127.0.0.1:<port>/healthz`.
  6. Exit non-zero on any step.
- **Backups:** user timer `organize-music-backup.timer`, nightly `organize-music db backup`.

## 11. Test strategy
- **Pure modules** (naming, paths, planners, reconcile diff, audio range parsing, error map): table
  tests, 100% branch coverage.
- **fsops:** run against `tmp_path`. On macOS this exercises `renamex_np` on case-insensitive
  APFS. `OM_FS_TEST_DIR` points the same suite at a directory on the Pi's exFAT SSD (§15).
- **Crash matrix (mandatory for every op kind):** `tests/support/faulty_fs.py` wraps `FsOps` and
  raises `SimulatedCrash` before or after the n-th call; `FaultyOplog` does the same around state
  writes. For every n, run the op, crash, run recovery on a fresh engine with the real fs, then
  assert:
  - `assert_consistent` holds: the multiset of file-content hashes under the root, the purge folder, and
    `tmp/` covers the originals; every `present` row matches disk; no active operations remain;
  - the op ended `committed`, or `failed` with the disk unchanged.
- **Collision, precondition-failed, and stale-preview tests** for each planner and route.
- **Web:** TestClient for every route, covering auth required, CSRF missing (403), wrong Host
  (400), traversal attempts (422), symlink escape (422), and mutations disabled (403).
- **E2E:** an in-process flow test (scan → list → preview rename → confirm → job done → undo) on
  a temp library, plus one Playwright smoke test marked `e2e` (opt-in).
- **Quality gate:** `ruff check . && ruff format --check . && pytest` with coverage ≥ 80% overall,
  100% on pure modules, and a 200-line file-length test over `src/`.

## 12. Phases

**Real-library gate:** nothing mutates the real library until Phases 0–8 are complete, the
end-of-phase reviews pass, and the owner turns on `mutations_enabled`. Read-only scan and hash may
run against the real library from Phase 3 on.

| Phase | Deliverable | Implements | Reviews |
|-------|-------------|-----------|---------|
| **0 Stabilise** | branch green and honest; deploy no longer deletes state | Qwen3.8 27 | Sonnet 5.5 per issue (as run: the local `hermes-review` reviewer, `REVIEWER_MODEL=gemma4:31b-mlx` per commit `22a42ef`; 6ut.8 by Claude); Opus 5.5 end of phase |
| **1 Tracer bullet** | new DB and migrations, oplog, one journaled move with recovery, `/files` list, rename-one page; Mac, then Pi on throwaway copies | Qwen3.8 27; **fsops by Opus 5.5** | Opus 5.5 for every mutation-path issue; Fable 5.2 reviews fsops; owner + Opus for Pi verification |
| **2 Foundations** | errors, job worker, full scan with tags, reconcile diff, auth, CSRF, paging, search, backups | Qwen3.8 27 | Opus 5.5 (worker, security, reconcile); Sonnet 5.5 (rest) |
| **3 Hashing + duplicates** | audio-payload hash (`8su`), hash job, duplicates page | Qwen3.8 27 | Opus 5.5 (hash ranges); Sonnet 5.5 (UI) |
| **4 Pattern rename + move** | vocabulary, pattern planner with `-copy-N`, art follows audio, folder handling, preview and confirm UI | Qwen3.8 27 | Opus 5.5 (planner, dirs); Sonnet 5.5 (UI) |
| **5 Metadata editing** | tag writer, retag op and recovery, batch runner, edit UI, edit + re-path | Qwen3.8 27 | Opus 5.5 (all mutation); Sonnet 5.5 (UI); owner + Opus Pi check |
| **6 Undo** | inverse planner, history and undo UI | Qwen3.8 27 | Opus 5.5 |
| **7 Drift UI** | drift and recovery pages | Qwen3.8 27 | Sonnet 5.5; Opus 5.5 end of phase |
| **8 Deployment** | systemd units, deploy script, backups timer, legacy CLI re-pointed or retired | Qwen3.8 27 | Opus 5.5; **owner + Opus** for first real-library read-only run, then the gate |
| **9 Later** | quarantine (`cpc`), Chromaprint (`hpg`), parser bug (`p1b`), byte-exact restore from the purge folder | per issue | |

**Why this order:**
- Foundations come first: everything long runs as a job, and the server needs auth before it binds
  to the LAN.
- Hashing comes before any tag write: the retag step's corruption check *is* the audio hash, and
  the duplicates view gives safe, read-only value on the real library early.
- Pattern rename comes before editing: it reuses the move op the tracer already proved, so the
  second mutation kind (retag) arrives on a tested batch runner. Edit + re-path needs both.
- Undo, drift, and deployment complete the safety story before the gate opens.

## 13. Tracker reconciliation
| Issue | Action | Reason |
|-------|--------|--------|
| `2k2` (in progress, lease expired) | release the lease; rewrite as "naming.py: finish sanitising in render_name"; close when Phase 0 issue P0-4 lands | pure parts landed; the report and CLI are superseded by the UI preview |
| `z80` (names CLI) | supersede by P4-6 (pattern preview page) | preview moves to the UI (Q-5) |
| `cvf` (closed, apply is a TODO) | reopen, then supersede by P4-2; code removed in P0-3 | closed without the apply step working |
| `dpf` (organize) | supersede by the Phase 4 epic | single mutation path |
| `cpc` (quarantine) | keep; rewrite description per C4; parent Phase 9 epic; depends on P4-4 and P3-5 | still wanted, now a batch kind |
| `3d1` (web UI, in progress, no code) | release the lease; supersede by the Phase 1 epic | replaced by this plan |
| `8su` (audio hash) | rewrite per C3; raise to P1; parent Phase 3; becomes a prerequisite | prerequisite for safe tag writes |
| `hpg` | keep; defer to Phase 9 (P4 priority) | not needed for v1 |
| `p1b` | keep as is; Phase 9 | unrelated parser bug |
| `3z4` (closed decision) | add a note pointing to C5 and C6 (owner answered Q-1 and Q-2 on 2026-11-17) | record the reversal |
| `docs/TASKS.md` | replace the body with a pointer to beads and this plan (P0-8) | out of date |

## 14. Owner decisions (answered 2026-11-17)

| Q | Decision | Where | Status |
|---|----------|-------|--------|
| 1 | Automatic rule-based `-copy-N` on collision, previewed, never overwrites | C5 | decided |
| 2 | Track number leads the filename; skipped when missing | C6 | decided |
| 2a | Disc option A: number-prefix rules N1–N5 | C6 | decided |
| 3 | Single password, bound to the Pi's LAN address, plain HTTP | §9.4 | decided |
| 4 | Tags live in the file; the DB holds a copy; edits write the file; mp3 and m4a only | C7 | decided |
| 5 | No CLI mutations; the UI is the only way to change files | C4 | decided |
| 6 | Replaced originals go to `purge/`, mirroring the library folder structure; the owner empties it by hand | §6.9 | decided |
| 7 | Album art moves with its audio | §6.8 | decided |
| 8 | Editing a field re-applies the pattern only to already-organised files | C6, P5-5 | decided |
| 9 | App waits for the drive and blocks scans and changes until it is mounted; a boot-time fstab mount is optional, owner-run, outside this project | §6.5 | decided |

## 15. Unverified assumptions (checked in the tracer, Phase 1)
- `renameat2(RENAME_NOREPLACE)` works on the Pi's exFAT (the Linux exFAT driver accepts the flag
  since 5.7, from memory). If it doesn't, the plan needs a design issue before any move ships.
- `fsync` on a directory fd works on exFAT under Linux.
- The Pi's Python `sqlite3` has FTS5.
- mediafile can keep a file's existing ID3 version (per-instance `id3v23`), and a mediafile write
  leaves the mp3 payload and the m4a `mdat` bytes unchanged. P3 and P5 tests prove the latter on
  fixtures; the Pi check proves it on real files from a throwaway copy.
- The Pi's actual config may already move the index out of `~/organize_music/state/`; not checked.

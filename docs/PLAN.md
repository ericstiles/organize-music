# Plan

Status: **Draft for review** · Written 2026-11-03

Inputs: the owner's answers (2026-11-03) and [LIBRARY_SURVEY.md](LIBRARY_SURVEY.md).
Detailed contracts are in [SPECS.md](SPECS.md). The phase checklist is in
[TASKS.md](TASKS.md). Once this plan is approved, work is tracked in beads (`bd ready`).

## Decisions

| # | Question | Decision |
|---|----------|----------|
| 1 | What comes first | **Metadata first.** CLI first; web UI later (separate beads issue). |
| 2 | Where it runs | On the **Pi 5** (`the-pi`, `pi-host`), against the library in place. Development and tests on the Mac. |
| 3 | Library shape | Surveyed directly: see [LIBRARY_SURVEY.md](LIBRARY_SURVEY.md). |
| 4 | Naming | A naming *template* is stored in config and can be changed later; `names` only **previews** it. Example (not final): `${album}-${artist}-${track}.${ext}`. **Renaming/moving happens only in the dedicated `organize` command, and only with `--apply`.** Every other command is read-only on the library (Phase 5's `quarantine` is the one other `--apply` command, for duplicates after organizing). |
| 5 | Duplicates | **Whole-file MD5**, but only for files whose byte size matches another file's. Audio-only hashing (ignores tag differences) is a follow-up. **Report only for now** (2026-11-03): no keeper is chosen and nothing is moved until after organizing. |
| 6 | Risk | **Mid-level.** Dry-run is the default. `--apply` is required to change anything. Nothing is hard-deleted: losing copies move to a quarantine folder. Every move or rename goes into an append-only journal, and `undo` can put files back. |
| 7 | Tracking and output | Beads is set up after this plan is written. **Every key report the tool produces is a Markdown file** (plus a machine-readable JSON/SQLite copy where it helps). |

### Why MD5, and what it misses

- Byte-identical copies (the survey's biggest signal) are caught exactly by
  any full-file hash. MD5 is fine here because nobody is forging collisions.
  It is fast on ARM and matches `md5sum` for manual checks.
- **What it misses:** the same recording where only the *tags* differ, which is
  common after an iTunes or iPod round-trip. Different bytes give a different MD5.
  The follow-up fix is an **audio-payload hash**: hash the audio frames and
  skip the ID3 or MP4 metadata atoms. Also out of scope for now: matching the
  same song at a different bitrate or encoding. That would need Chromaprint
  (`fpcalc`), which isn't installed.
- Size pre-filter: a file with a unique byte size can't be a byte-identical
  duplicate, so it is never hashed. (On this library ~94% share a size, so the
  savings are small, but it's free.)

## Architecture

```
src/organize_music/
  config.py        library root, index path, quarantine dir, name template, path-preference rules
  models.py        frozen dataclasses: TrackMetadata, FileRecord, DupGroup, JournalEntry
  scanner.py       walk the tree -> FileRecord (path, size, mtime, ext); no tag reads
  metadata.py      pure: tag dict + path -> TrackMetadata, with a source for each field
  tag_reader.py    side effect: mutagen -> raw tag dict (the only module importing mutagen)
  filename_parse.py pure: "(Genre) Artist - Title(1).mp3" -> partial fields
  index_db.py      SQLite repository (stdlib sqlite3): upsert/find records, resumable state
  hashing.py       chunked md5 of a file; skip if size+mtime unchanged since last hash
  dedup.py         pure: records -> DupGroups, keeper chosen by path-preference rules
  naming.py        pure: template + TrackMetadata -> proposed filename (sanitised)
  journal.py       append-only JSONL of every applied operation; reader for undo
  fileops.py       side effect: move-to-quarantine / rename, ONLY via journal
  reports.py       pure: data -> Markdown report text
  cli.py           argparse entry point `organize-music`
```

Each file stays under 200 lines. Pure modules take data in and return data;
only `scanner`, `tag_reader`, `hashing`, `index_db`, `journal` and `fileops`
touch disk.

**State lives in one SQLite index**: `~/.local/share/organize_music/index.db`
on the Pi, outside the library. With 100k rows, `scan` and `hash` can resume
after an interruption, and `report` can re-run without touching the disk again.

## CLI (`organize-music`)

| Command | Changes files? | Output |
|---------|----------------|--------|
| `scan` | no | index updated; `reports/SCAN_REPORT.md` (counts by type/depth, unreadable files) |
| `meta` | no | tags read into the index; `reports/METADATA_REPORT.md` (missing fields, tag vs. filename disagreements) |
| `names --template T` | no | `reports/NAME_PREVIEW.md` (current name → proposed name, collisions) |
| `hash` | no | MD5s for size-collision files; resumable, with progress |
| `dupes` | no | `reports/DUPLICATES_REPORT.md` (groups, every path, reclaimable space; no keeper) |
| `organize` | **only with `--apply`** | moves files into the templated folder structure; journal entry for each move; collisions left in place and reported |
| `quarantine` | **only with `--apply`** | after organizing: moves duplicate leftovers to `<quarantine>/<original relative path>`; journal entry for each move |
| `undo JOURNAL` | **only with `--apply`** | moves everything in that journal back to its original path |

`--dry-run` is implied unless `--apply` is passed. Reports are written to
`reports/` (configurable) with a timestamped copy kept alongside.

## Safety model

1. **Journal before the move.** Write a JSONL entry with `{op, src, dst, md5, size, ts}`
   and fsync it. Only then do the move. After the move, verify that the
   destination's size matches, and record `done`.
2. **Quarantine instead of delete.** The quarantine folder lives on the same
   SSD (so a move is an instant rename, using no extra space) but outside the
   library root. It keeps the original relative path, so a file's origin is
   obvious even without the journal.
3. **No overwrites.** If a destination already exists, that file is left where
   it is and listed in the report. A byte-identical collision is a duplicate
   for the later duplicates step; a different-content collision needs a human.
4. **Fail fast:** the library root must exist and be mounted, the
   quarantine folder must be on the same device, and the journal must be
   writable. All three are checked before the first move.
5. Emptying the quarantine is left to the owner. The tool never runs `rm`.

## Phases

| Phase | Deliverable | Changes files? |
|-------|-------------|----------------|
| **0 Tracer bullet** | `scan` + `meta` on 1 folder, Mac then Pi, end-to-end to a Markdown report | no |
| **1 Metadata** | full `meta` over the library, field sources, filename fallback parser, METADATA_REPORT | no |
| **2 Naming preview** | configurable template, sanitising, collision detection, NAME_PREVIEW | no |
| **3 Duplicates report** | resumable `hash`, `dupes` → DUPLICATES_REPORT (report only, no keeper) | no |
| **4 Organize** (`organize_music-dpf`) | journal, `organize --apply` into the templated folder structure, `undo --apply` | **yes** |
| **5 Address duplicates** (`organize_music-cpc`) | choose keepers among what's left, `quarantine --apply`, `undo --apply` | **yes** |
| Done | Pi deployment: `scripts/deploy_to_pi.sh` (rsync + venv), long-running jobs under `tmux` | no |
| Later | web UI front end over the index (`organize_music-3d1`); audio-payload hash (`organize_music-8su`); Chromaprint fingerprint for different encodings (`organize_music-hpg`); actually applying renames | |

Phases 0–3 never change the library. The first phase that can is Phase 4
(organize), and only after you've reviewed NAME_PREVIEW and DUPLICATES_REPORT.
Duplicates are acted on only after organizing (Phase 5).

## Open questions

- **Target folder format** (before Phase 4): e.g. `${artist}/${album}/${track}-${title}.${ext}`.
  Decide after reading NAME_PREVIEW from Phase 2.
- **Keeper preference** (before Phase 5 only): which copy stays when duplicates
  are acted on. Deferred until after organizing.
- **Quarantine location:** suggested `/path/to/library-parent/_quarantine`
  (same disk, outside `Music/`).
- **Final name template:** decide after reading NAME_PREVIEW from Phase 2.

# Examples

Worked examples for the `organize-music` CLI.

**Where it runs:** the tools run **on the Pi** (`the-pi`, `pi-host`),
against the music library in place. You develop and run the tests on the Mac,
then deploy to the Pi to run against the real library. Every command here is
**read-only**: the tools stat and hash files and write Markdown reports, but
never move, rename, or delete anything in the library.

| Thing | Value |
|-------|-------|
| Pi host | `user@pi-host` (`ssh user@pi-host`) |
| Library root (on the Pi) | `/path/to/library-parent/Music` |
| Install dir (on the Pi) | `~/organize_music` (its own `.venv`) |
| Index (default) | `~/.local/share/organize_music/index.db` |

## 1. Deploy from the Mac

From the repo root on the Mac, push the code to the Pi and install it into a
venv there. This touches only `~/organize_music` on the Pi — never the music
library.

```bash
scripts/deploy_to_pi.sh
# override the defaults if needed:
PI_HOST=user@pi-host PI_DIR=organize_music scripts/deploy_to_pi.sh
```

The script rsyncs the repo, creates `~/organize_music/.venv`, runs
`pip install .` (which puts the `organize-music` entry point on the venv's
PATH), and verifies `organize-music --help`.

## 2. Run on the Pi

SSH in and run long jobs under `tmux` so they survive a dropped connection.

```bash
ssh user@pi-host
tmux new -s music                      # detach with Ctrl-b d, reattach: tmux attach -t music
cd ~/organize_music
source .venv/bin/activate
```

The three commands, against the real library:

```bash
LIB=/path/to/library-parent/Music

organize-music meta  "$LIB" --report ~/organize_music/reports/METADATA_REPORT.md
organize-music hash  "$LIB"
organize-music dupes "$LIB" --report ~/organize_music/reports/DUPLICATES_REPORT.md
```

> The index and reports **must live outside the library** — the CLI refuses
> paths inside the library root so a run never scans its own output. Keeping
> them under `~/organize_music/` (as above) satisfies that.

Pull a finished report back to the Mac:

```bash
# run on the Mac
scp user@pi-host:organize_music/reports/DUPLICATES_REPORT.md .
```

## The three commands

| Command | What it does | Output |
|---------|--------------|--------|
| `meta`  | Read tags (with a filename/folder fallback) | `METADATA_REPORT.md` |
| `hash`  | MD5 the files that share a byte size | SQLite hash index (resumable) |
| `dupes` | Report byte-identical files | `DUPLICATES_REPORT.md` |

All three share one resumable SQLite index, so a second run resumes instead of
re-reading everything. Interrupt any run with `Ctrl-C` — progress is saved to
the index, and the next run resumes where it stopped (handy for a multi-hour
first pass over the whole library).

### `meta` — metadata report

```bash
organize-music meta "$LIB" --report ~/organize_music/reports/METADATA_REPORT.md
```

```
Found 4213 files under /media/.../Music (index: ~/.local/share/organize_music/index.db)
4213 audio files (read 4213, cached 0, pruned 0, errors 12). Report: .../METADATA_REPORT.md
```

Re-run and already-read files come from the cache
(`read 0, cached 4213`). Flags: `--rescan` re-reads every tag; `--index PATH`
uses a specific index file.

### `hash` — MD5 size-collision candidates

Only files that share an exact byte size can be byte-identical, so `hash`
fingerprints just those candidates and stores the result in the index.

```bash
organize-music hash "$LIB"
```

```
# first run
7 candidate files (hashed 7, cached 0, failed 0, pruned 0); 0.00 GB read
2 groups of byte-identical files (5 files)

# second run — resumable
7 candidate files (hashed 0, cached 7, failed 0, pruned 0); 0.00 GB read
2 groups of byte-identical files (5 files)
```

Use `--rehash` to ignore cached hashes and recompute them.

### `dupes` — duplicates report

Group byte-identical files by MD5 and write a report. **Report only**: it picks
no keeper and moves nothing. It reuses hashes already in the index.

```bash
organize-music dupes "$LIB" --report ~/organize_music/reports/DUPLICATES_REPORT.md
```

```
2 groups, 3 extra copies, 0.00 GB reclaimable (hashed 0, cached 7, failed 0). Report: .../DUPLICATES_REPORT.md
```

Sample `DUPLICATES_REPORT.md`:

```markdown
# Duplicates Report

- Report only: no keeper is chosen and no files were moved.
- Byte-identical = same MD5. Same song with different tags is not detected yet.

## Duplicate groups (largest reclaimable space first)

### 1. 3 copies (md5 `ece7d69e...`)

- `Albums/Misc/lithium_copy.mp3`
- `Albums/Nirvana - Nevermind/03 Nirvana - Lithium.mp3`
- `ipod_backup/track_1234.mp3`
```

## Typical first-run workflow on the Pi

```bash
ssh user@pi-host
tmux new -s music
cd ~/organize_music && source .venv/bin/activate
LIB=/path/to/library-parent/Music

organize-music meta  "$LIB" --report ~/organize_music/reports/METADATA_REPORT.md
organize-music hash  "$LIB"
organize-music dupes "$LIB" --report ~/organize_music/reports/DUPLICATES_REPORT.md
# Ctrl-b d to detach; come back later with: tmux attach -t music
```

## Local development on the Mac

For running the tests or trying commands against a small sample folder locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .                    # installs the `organize-music` entry point
pip install -r requirements-dev.txt # pytest, ruff, mutagen (dev tools only)

ruff check . && ruff format --check . && pytest
```

> `requirements-dev.txt` installs the dev tools, **not** the package. The
> `organize-music` command only appears after `pip install -e .` (editable) or
> `pip install .`. On the Pi, `scripts/deploy_to_pi.sh` does this for you.

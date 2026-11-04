# Technical Specification

> **Feature / Component Name**: Library scan and metadata extraction (Phases 0–1)
> **Status**: Draft
> **Last Updated**: 2026-11-03
> **Plan**: [PLAN.md](PLAN.md) · **Survey**: [LIBRARY_SURVEY.md](LIBRARY_SURVEY.md)

---

## 1. Context & Objectives
- **Problem Statement**: The library has ~100k mp3/m4a files spread across
  1,504 folders with no consistent layout. Many tags are missing or unreliable.
  Naming changes and de-duplication can't be planned until we know what metadata
  each file actually has.
- **Scope**:
  - Walk the library and index every file.
  - Read tags from audio files.
  - Fill gaps from the filename and folder names, and record the source of
    every field.
  - Write a Markdown report.
- **Out of Scope**: renaming, hashing/dedup, any file changes, the web UI,
  editing tags.

## 2. Requirements & Acceptance Criteria
- [ ] **REQ-1**: `scan` indexes every file under the root (path, size, mtime, ext)
  and never opens a file for writing.
- [ ] **REQ-2**: `meta` reads tags for mp3, m4a, m4p, ogg, wma and wav with
  `mutagen`. Other extensions are counted in the report, not parsed.
- [ ] **REQ-3**: Every metadata field carries a source: `tag`, `filename`,
  `folder` or `missing`. If tag and filename disagree, the report lists it;
  the tool doesn't pick one silently.
- [ ] **REQ-4**: An unreadable or corrupt file is recorded with its error and
  the batch continues. It never crashes the run.
- [ ] **REQ-5**: Runs are resumable. A re-run skips files whose size and mtime
  haven't changed since they were last read.
- [ ] **REQ-6**: `reports/METADATA_REPORT.md` summarizes:
  - counts by extension
  - % of files with each field from tags
  - the top folders with missing tags
  - errors
  - a sample of tag/filename disagreements
- [ ] **REQ-7**: 100% branch coverage on the pure modules
  (`metadata.py`, `filename_parse.py`, `reports.py`); 80%+ overall.

## 3. Data Contracts & Interfaces

```python
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Source(StrEnum):
    TAG = "tag"
    FILENAME = "filename"
    FOLDER = "folder"
    MISSING = "missing"


@dataclass(frozen=True)
class Field:
    value: str | int | None
    source: Source


@dataclass(frozen=True)
class FileRecord:
    path: Path              # relative to the library root
    size: int
    mtime_ns: int
    ext: str                # lower-case, no dot


@dataclass(frozen=True)
class TrackMetadata:
    record: FileRecord
    artist: Field
    album_artist: Field
    album: Field
    title: Field
    track_number: Field
    disc_number: Field
    year: Field
    genre: Field
    duration_seconds: float | None
    bitrate_kbps: int | None
    error: str | None       # set when the file could not be read


# pure
def parse_filename(stem: str) -> dict[str, str | int]: ...
def build_metadata(record: FileRecord, raw_tags: dict[str, str], folders: list[str]) -> TrackMetadata: ...
def render_metadata_report(rows: list[TrackMetadata]) -> str: ...

# side effects
def walk_library(root: Path) -> Iterator[FileRecord]: ...
def read_raw_tags(path: Path) -> dict[str, str]: ...   # raises TagReadError
```

## 4. Safety, Edge Cases & Error Handling
- **Read-only:** no module in this phase calls a write, move or delete on the
  library. A test asserts that `fileops` is not imported by `scan` or `meta`.
- **Filename patterns seen in the library** (all must have tests):
  - `(Genre) Artist - Title.mp3`
  - `(Genre) - Artist - Title.mp3`
  - `01 Title.mp3`
  - `01 - Artist - Title.mp3`
  - `01 - 12 - Title.mp3`
  - `Title(1).mp3` (copy suffix)
  - `.MP3` (upper-case extension)
- **Folder names** like `[Indie Folk] Artist - Album 2016 (Uploader)` and
  `(1998) u2 The Best Of 1980-1990 By X`: extract artist, album and year when
  the pattern matches. Otherwise the field is `missing`, not a guess.
- **Unicode / odd characters:** keep the original paths as given. Don't
  normalize them on disk. NFC-normalize only for comparisons.
- **m4p (DRM):** read the tags, and mark audio as protected in the report.
- **Zero-byte or truncated files:** set `error` and continue.
- **Library not mounted:** fail fast if the root is missing or empty.

## 5. Verification Plan
- **Unit**: pure parsers and builders with table-driven tests built from real
  filenames in the survey.
- **Fixtures**: tiny generated mp3/m4a files (silence) in `tests/fixtures/`,
  tagged via mutagen in a session fixture. No copyrighted audio.
- **Integration**: `scan` + `meta` against a temp tree mimicking the survey's
  layout; check the Markdown report text.
- **Live (tracer bullet)**: run on the Pi against one real folder
  (e.g. `Carbon Leaf`), read the report, then run the full library.

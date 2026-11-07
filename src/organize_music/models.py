"""Immutable data models shared across the package."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class Source(StrEnum):
    """Where a metadata value came from."""

    TAG = "tag"
    FILENAME = "filename"
    FOLDER = "folder"
    MISSING = "missing"


@dataclass(frozen=True)
class Field:
    """A metadata value plus its provenance."""

    value: str | int | None
    source: Source


MISSING = Field(value=None, source=Source.MISSING)


@dataclass(frozen=True)
class FileRecord:
    """One file found under the library root."""

    path: Path  # relative to the library root
    size: int
    mtime_ns: int
    ext: str  # lower-case, no leading dot


@dataclass(frozen=True)
class RawTags:
    """Tags and audio info exactly as read from a file, before interpretation."""

    tags: Mapping[str, str]
    duration_seconds: float | None
    bitrate_kbps: int | None


@dataclass(frozen=True)
class RawTagDump:
    """Every stored tag as (key, value) pairs in file order, plus audio info.

    Unlike RawTags, this keeps all keys and all values from the non-"easy"
    interface (composer, comments, album art, multi-values), for `tags --raw`.
    """

    items: tuple[tuple[str, str], ...]
    duration_seconds: float | None
    bitrate_kbps: int | None


@dataclass(frozen=True)
class ReadFailure:
    """A file that could not be parsed as audio."""

    error: str


ReadResult = RawTags | ReadFailure


@dataclass(frozen=True)
class TrackMetadata:
    """Interpreted metadata for one audio file."""

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
    error: str | None  # set when the file could not be read


FIELD_NAMES: tuple[str, ...] = (
    "artist",
    "album_artist",
    "album",
    "title",
    "track_number",
    "disc_number",
    "year",
    "genre",
)

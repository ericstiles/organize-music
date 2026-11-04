"""Pure interpretation of raw tags into TrackMetadata. No disk access."""

import re
from collections.abc import Callable, Mapping

from organize_music.filename_parse import Parsed, parse_filename, parse_folders
from organize_music.models import (
    MISSING,
    Field,
    FileRecord,
    RawTags,
    ReadFailure,
    ReadResult,
    Source,
    TrackMetadata,
)

AUDIO_EXTS: frozenset[str] = frozenset({"mp3", "m4a", "m4p", "ogg", "wma", "wav", "flac"})
MIN_YEAR = 1900
MAX_YEAR = 2100

_LEADING_INT = re.compile(r"^\s*(\d+)")
_LEADING_YEAR = re.compile(r"^\s*(\d{4})(?!\d)")


def is_audio(record: FileRecord) -> bool:
    return record.ext in AUDIO_EXTS


def _text(value: str | None) -> str | int | None:
    stripped = (value or "").strip()
    return stripped or None


def _position(value: str | None) -> str | int | None:
    """'3', '3/12', ' 07 ' -> 3/3/7; zero or non-numeric -> None."""
    match = _LEADING_INT.match(value or "")
    number = int(match.group(1)) if match else 0
    return number or None


def _year(value: str | None) -> str | int | None:
    match = _LEADING_YEAR.match(value or "")
    year = int(match.group(1)) if match else 0
    return year if MIN_YEAR <= year <= MAX_YEAR else None


def _tag_field(
    tags: Mapping[str, str], key: str, parse: Callable[[str | None], str | int | None]
) -> Field:
    value = parse(tags.get(key))
    return MISSING if value is None else Field(value=value, source=Source.TAG)


def _fallback(field: Field, name: str, from_file: Parsed, from_folders: Parsed) -> Field:
    """Tag wins; else filename; else folder; else MISSING."""
    if field.source is not Source.MISSING:
        return field
    if name in from_file:
        return Field(value=from_file[name], source=Source.FILENAME)
    if name in from_folders:
        return Field(value=from_folders[name], source=Source.FOLDER)
    return field


def build_metadata(record: FileRecord, raw: RawTags) -> TrackMetadata:
    """Interpret raw tags, filling gaps from the filename then the folders.

    Values that can't be found or parsed are MISSING, never guessed.
    """
    tags = raw.tags
    from_file = parse_filename(record.path.stem)
    from_folders = parse_folders(record.path)

    def field(name: str, key: str, parse: Callable[[str | None], str | int | None]) -> Field:
        return _fallback(_tag_field(tags, key, parse), name, from_file, from_folders)

    return TrackMetadata(
        record=record,
        artist=field("artist", "artist", _text),
        album_artist=field("album_artist", "albumartist", _text),
        album=field("album", "album", _text),
        title=field("title", "title", _text),
        track_number=field("track_number", "tracknumber", _position),
        disc_number=field("disc_number", "discnumber", _position),
        year=field("year", "date", _year),
        genre=field("genre", "genre", _text),
        duration_seconds=raw.duration_seconds,
        bitrate_kbps=raw.bitrate_kbps,
        error=None,
    )


def error_metadata(record: FileRecord, error: str) -> TrackMetadata:
    """Metadata for a file that could not be read: every field MISSING."""
    return TrackMetadata(
        record=record,
        artist=MISSING,
        album_artist=MISSING,
        album=MISSING,
        title=MISSING,
        track_number=MISSING,
        disc_number=MISSING,
        year=MISSING,
        genre=MISSING,
        duration_seconds=None,
        bitrate_kbps=None,
        error=error,
    )


def interpret(record: FileRecord, result: ReadResult) -> TrackMetadata:
    """Turn a raw read (or a read failure) into TrackMetadata."""
    if isinstance(result, ReadFailure):
        return error_metadata(record, result.error)
    return build_metadata(record, result)

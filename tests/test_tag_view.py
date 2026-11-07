"""Tests for pure tag rendering (no disk access)."""

from pathlib import Path

from organize_music.metadata import error_metadata
from organize_music.models import MISSING, Field, FileRecord, Source, TrackMetadata
from organize_music.tag_view import render_tags


def record(name: str = "Zammuto/Zammuto/01 Yay.mp3") -> FileRecord:
    return FileRecord(path=Path(name), size=10, mtime_ns=1, ext=Path(name).suffix[1:].lower())


def track(**over: object) -> TrackMetadata:
    """Build a TrackMetadata with every field MISSING unless overridden."""
    base: dict[str, object] = {
        "record": record(),
        "artist": MISSING,
        "album_artist": MISSING,
        "album": MISSING,
        "title": MISSING,
        "track_number": MISSING,
        "disc_number": MISSING,
        "year": MISSING,
        "genre": MISSING,
        "duration_seconds": None,
        "bitrate_kbps": None,
        "error": None,
    }
    base.update(over)
    return TrackMetadata(**base)  # type: ignore[arg-type]


def test_render_shows_the_path_header() -> None:
    text = render_tags(track())

    assert text.splitlines()[0] == "Zammuto/Zammuto/01 Yay.mp3"


def test_render_shows_tag_values_with_their_source() -> None:
    text = render_tags(
        track(
            artist=Field("Zammuto", Source.TAG),
            title=Field("Yay", Source.TAG),
            year=Field(2012, Source.TAG),
        )
    )

    assert "Zammuto  (tag)" in text
    assert "Yay  (tag)" in text
    assert "2012  (tag)" in text


def test_render_marks_missing_fields() -> None:
    text = render_tags(track(title=Field("Yay", Source.TAG)))

    assert "(missing)" in text  # artist, album, etc. are all MISSING


def test_render_shows_non_tag_provenance() -> None:
    text = render_tags(track(title=Field("Yay", Source.FILENAME)))

    assert "Yay  (filename)" in text


def test_duration_and_bitrate_shown_when_present() -> None:
    text = render_tags(track(duration_seconds=219.3, bitrate_kbps=160))

    assert "219 s" in text
    assert "160 kbps" in text


def test_duration_and_bitrate_omitted_when_absent() -> None:
    text = render_tags(track())

    assert "kbps" not in text
    assert "duration" not in text


def test_error_track_renders_an_error_line_and_no_fields() -> None:
    text = render_tags(error_metadata(record("broken.mp3"), "unrecognised audio format"))

    assert "broken.mp3" in text
    assert "unrecognised audio format" in text
    assert "(missing)" not in text  # an unreadable file reports the error, not 8 blanks

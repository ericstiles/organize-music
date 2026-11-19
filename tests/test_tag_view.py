"""Tests for pure tag rendering (no disk access)."""

from pathlib import Path

from organize_music.metadata import error_metadata
from organize_music.models import (
    MISSING,
    Field,
    FileRecord,
    RawTagDump,
    ReadFailure,
    Source,
    TrackMetadata,
)
from organize_music.tag_view import render_raw, render_tags


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


def test_render_shows_tag_values_without_a_tag_label() -> None:
    text = render_tags(
        track(
            artist=Field("Zammuto", Source.TAG),
            title=Field("Yay", Source.TAG),
            year=Field(2012, Source.TAG),
        )
    )

    assert "Zammuto" in text
    assert "Yay" in text
    assert "2012" in text
    assert "(tag)" not in text  # a plain embedded tag carries no provenance label


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


def test_render_raw_lists_every_pair_without_provenance() -> None:
    dump = RawTagDump(
        items=(("TPE1", "Zammuto"), ("TXXX:ISRC", "US-ABC-12")),
        duration_seconds=219.0,
        bitrate_kbps=160,
    )

    text = render_raw("01 Yay.mp3", dump)

    assert text.splitlines()[0] == "01 Yay.mp3"
    assert "TPE1" in text and "Zammuto" in text
    assert "TXXX:ISRC" in text and "US-ABC-12" in text  # a non-curated tag is still shown
    assert "219 s" in text and "160 kbps" in text
    assert "(tag)" not in text  # raw mode never labels provenance


def test_render_raw_reports_a_read_failure() -> None:
    text = render_raw("broken.mp3", ReadFailure(error="unrecognised audio format"))

    assert "broken.mp3" in text
    assert "unrecognised audio format" in text


def test_render_raw_omits_audio_info_when_absent() -> None:
    # A raw dump with no duration/bitrate lists only the tag pairs.
    dump = RawTagDump(items=(("TPE1", "Zammuto"),), duration_seconds=None, bitrate_kbps=None)

    text = render_raw("01 Yay.mp3", dump)

    assert text.splitlines()[0] == "01 Yay.mp3"
    assert "TPE1" in text and "Zammuto" in text
    assert "kbps" not in text
    assert "duration" not in text


def test_render_raw_shows_only_duration() -> None:
    # A raw dump with a duration but no bitrate exercises the duration branch only.
    dump = RawTagDump(items=(("TPE1", "Zammuto"),), duration_seconds=219.0, bitrate_kbps=None)

    text = render_raw("01 Yay.mp3", dump)

    assert "219 s" in text
    assert "kbps" not in text

"""Tests for pure metadata building (no disk access)."""

from pathlib import Path

import pytest

from organize_music.metadata import build_metadata, error_metadata, interpret, is_audio
from organize_music.models import Field, FileRecord, RawTags, ReadFailure, Source


def record(name: str = "a.mp3") -> FileRecord:
    return FileRecord(path=Path(name), size=10, mtime_ns=1, ext=Path(name).suffix[1:].lower())


def raw(**tags: str) -> RawTags:
    return RawTags(tags=tags, duration_seconds=200.5, bitrate_kbps=192)


def test_tag_values_are_marked_with_tag_source() -> None:
    meta = build_metadata(record(), raw(artist="Prince", title="Purple Rain"))

    assert meta.artist.value == "Prince"
    assert meta.artist.source is Source.TAG
    assert meta.title.value == "Purple Rain"
    assert meta.duration_seconds == 200.5
    assert meta.bitrate_kbps == 192
    assert meta.error is None


def test_absent_and_blank_tags_are_missing_not_guessed() -> None:
    meta = build_metadata(record(), raw(artist="   "))

    assert meta.artist.source is Source.MISSING
    assert meta.artist.value is None
    assert meta.album.source is Source.MISSING


@pytest.mark.parametrize(
    ("value", "expected"),
    [("3", 3), ("3/12", 3), (" 07 ", 7), ("A", None), ("0", None)],
)
def test_track_number_parsing(value: str, expected: int | None) -> None:
    meta = build_metadata(record(), raw(tracknumber=value))

    assert meta.track_number.value == expected
    assert meta.track_number.source is (Source.TAG if expected else Source.MISSING)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2001", 2001), ("2001-05-01", 2001), ("05/01/2001", None), ("1800", None)],
)
def test_year_parsing(value: str, expected: int | None) -> None:
    meta = build_metadata(record(), raw(date=value))

    assert meta.year.value == expected


def test_album_artist_and_genre_are_read() -> None:
    meta = build_metadata(record(), raw(albumartist="Various Artists", genre="Rock"))

    assert meta.album_artist.value == "Various Artists"
    assert meta.genre.value == "Rock"


def test_error_metadata_has_every_field_missing() -> None:
    meta = error_metadata(record(), "can't sync to MPEG frame")

    assert meta.error == "can't sync to MPEG frame"
    assert meta.title.source is Source.MISSING
    assert meta.duration_seconds is None


@pytest.mark.parametrize(
    ("ext", "expected"),
    [("mp3", True), ("m4a", True), ("m4p", True), ("ogg", True), ("jpg", False), ("exe", False)],
)
def test_is_audio(ext: str, expected: bool) -> None:
    assert is_audio(FileRecord(path=Path("x"), size=1, mtime_ns=1, ext=ext)) is expected


def test_filename_fills_fields_missing_from_tags() -> None:
    meta = build_metadata(record("01 - De La Soul - Me Myself And I.mp3"), raw())

    assert meta.artist == Field("De La Soul", Source.FILENAME)
    assert meta.title == Field("Me Myself And I", Source.FILENAME)
    assert meta.track_number == Field(1, Source.FILENAME)


def test_tags_win_over_filename_and_folder() -> None:
    meta = build_metadata(record("Queen/1975 - Queen II/01 Wrong.mp3"), raw(title="Right"))

    assert meta.title == Field("Right", Source.TAG)


def test_folder_fills_what_filename_cannot() -> None:
    meta = build_metadata(record("Queen/1975 - Queen II/01 Father To Son.mp3"), raw())

    assert meta.artist == Field("Queen", Source.FOLDER)
    assert meta.album == Field("Queen II", Source.FOLDER)
    assert meta.year == Field(1975, Source.FOLDER)
    assert meta.title == Field("Father To Son", Source.FILENAME)


def test_filename_beats_folder() -> None:
    meta = build_metadata(record("Queen/Greatest/Freddie - Bohemian.mp3"), raw())

    assert meta.artist == Field("Freddie", Source.FILENAME)


def test_interpret_dispatches_on_read_result() -> None:
    ok = interpret(record(), raw(artist="X"))
    failed = interpret(record(), ReadFailure(error="bad frame"))

    assert ok.artist.value == "X"
    assert failed.error == "bad frame"
    assert failed.title.source is Source.MISSING


def test_build_metadata_honours_skip_folders() -> None:
    skip = frozenset({"Music2"})
    rec = FileRecord(path=Path("Music2/Candlebox/01 Far Behind.mp3"), size=1, mtime_ns=1, ext="mp3")

    meta = build_metadata(rec, raw(), skip_folders=skip)

    # Artist/album NOT taken from the collection folder; title still from filename.
    assert meta.artist.source is Source.MISSING
    assert meta.album.source is Source.MISSING
    assert meta.title == Field("Far Behind", Source.FILENAME)


def test_interpret_threads_skip_folders() -> None:
    skip = frozenset({"Music2"})
    rec = FileRecord(path=Path("Music2/Candlebox/01 Far Behind.mp3"), size=1, mtime_ns=1, ext="mp3")

    meta = interpret(rec, raw(), skip_folders=skip)

    assert meta.artist.source is Source.MISSING

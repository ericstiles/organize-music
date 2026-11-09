"""Tests for the pure naming module (Phase 2)."""
from organize_music.models import Field, FileRecord, Source, TrackMetadata
from organize_music.naming import render_name


def _track(artist="Carbon Leaf", album="Echo Echo", track=1, title="Learn To Fly", ext="mp3"):
    record = FileRecord(path=__import__("pathlib").Path("x.mp3"), size=1, mtime_ns=1, ext=ext)
    return TrackMetadata(
        record=record,
        artist=Field(value=artist, source=Source.TAG),
        album_artist=Field(value=None, source=Source.MISSING),
        album=Field(value=album, source=Source.TAG),
        title=Field(value=title, source=Source.TAG),
        track_number=Field(value=track, source=Source.TAG),
        disc_number=Field(value=None, source=Source.MISSING),
        year=Field(value=None, source=Source.MISSING),
        genre=Field(value=None, source=Source.MISSING),
        duration_seconds=None,
        bitrate_kbps=None,
        error=None,
    )


def test_render_name_basic():
    t = _track()
    assert render_name("${artist}/${album}/${track}-${title}.${ext}", t) == "Carbon Leaf/Echo Echo/1-Learn To Fly.mp3"


def test_render_name_missing_field_empty():
    t = _track(album=None)
    assert render_name("${artist}/${album}/${title}.${ext}", t) == "Carbon Leaf//Learn To Fly.mp3"


def test_render_name_unknown_placeholder_empty():
    t = _track()
    assert render_name("${nope}/${title}.${ext}", t) == "/Learn To Fly.mp3"

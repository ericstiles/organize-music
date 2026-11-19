"""Tests for NAME_PREVIEW report rendering (Phase 2)."""

from datetime import datetime
from pathlib import Path

from organize_music.models import Field, FileRecord, Source, TrackMetadata
from organize_music.reports import NamePreviewSummary, render_name_preview_report


def _track(artist="A", album="B", track=1, title="T", ext="mp3"):
    record = FileRecord(path=Path("x.mp3"), size=1, mtime_ns=1, ext=ext)
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


def test_render_name_preview():
    summary = NamePreviewSummary(
        root=Path("/lib"),
        generated_at=datetime(2026, 11, 9, 12, 0),
        template="${artist}/${album}/${track}-${title}.${ext}",
        rows=[(_track(), "A/B/1-T.mp3")],
        collisions={},
    )
    text = render_name_preview_report(summary)
    assert "# Name Preview" in text
    assert "A/B/1-T.mp3" in text


def test_render_name_preview_lists_collisions():
    # Two proposals sharing a target path surface a Collisions section.
    summary = NamePreviewSummary(
        root=Path("/lib"),
        generated_at=datetime(2026, 11, 9, 12, 0),
        template="${title}.${ext}",
        rows=[
            (_track(), "T.mp3"),
            (_track(), "T.mp3"),
        ],
        collisions={
            "T.mp3": [("src/a/T.mp3", "aabb"), ("src/b/T.mp3", "ccdd")],
        },
    )
    text = render_name_preview_report(summary)
    assert "## Collisions" in text
    assert "- `T.mp3`: 2 files" in text

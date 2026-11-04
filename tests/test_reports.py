"""Tests for pure Markdown report rendering."""

from datetime import datetime
from pathlib import Path

from organize_music.metadata import build_metadata, error_metadata
from organize_music.models import FileRecord, RawTags
from organize_music.reports import ScanSummary, render_metadata_report

WHEN = datetime(2026, 11, 3, 20, 0)


def rec(name: str) -> FileRecord:
    return FileRecord(path=Path(name), size=1, mtime_ns=1, ext=Path(name).suffix[1:].lower())


def summary() -> ScanSummary:
    full = RawTags(
        tags={"artist": "A", "album": "B", "title": "C", "tracknumber": "1", "date": "1999"},
        duration_seconds=1.0,
        bitrate_kbps=128,
    )
    rows = [
        build_metadata(rec("A/B/01 C.mp3"), full),
        build_metadata(
            rec("loose | pipe.mp3"), RawTags(tags={}, duration_seconds=None, bitrate_kbps=None)
        ),
        error_metadata(rec("broken.mp3"), "bad\nframe"),
    ]
    return ScanSummary(
        root=Path("/music"),
        generated_at=WHEN,
        ext_counts={"mp3": 3, "jpg": 1},
        tracks=rows,
    )


def test_report_has_header_and_totals() -> None:
    text = render_metadata_report(summary())

    assert text.startswith("# Metadata Report\n")
    assert "`/music`" in text
    assert "2026-11-03 20:00" in text
    assert "| Files scanned | 4 |" in text
    assert "| Audio files read | 3 |" in text
    assert "| Read errors | 1 |" in text


def test_report_lists_extension_counts_largest_first() -> None:
    text = render_metadata_report(summary())

    assert text.index("| mp3 | 3 |") < text.index("| jpg | 1 |")


def test_report_shows_field_coverage_over_readable_tracks() -> None:
    text = render_metadata_report(summary())

    assert "| artist | 1 | 50.0% | 0 | 0 | 1 |" in text
    assert "| title | 1 | 50.0% | 1 | 0 | 0 |" in text
    assert "| genre | 0 | 0.0% | 0 | 0 | 2 |" in text


def test_report_lists_errors_and_untagged_files_escaped() -> None:
    text = render_metadata_report(summary())

    assert "| `broken.mp3` | bad frame |" in text
    assert "`loose \\| pipe.mp3`" in text


def test_report_handles_no_tracks() -> None:
    empty = ScanSummary(root=Path("/m"), generated_at=WHEN, ext_counts={}, tracks=[])

    text = render_metadata_report(empty)

    assert "| Audio files read | 0 |" in text
    assert "_None._" in text

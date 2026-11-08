"""Tests for the mutagen-backed tag reader (the only module touching mutagen)."""

from pathlib import Path

import pytest

from organize_music.tag_reader import TagReadError, read_all_tags, read_tags


def test_reads_mp3_tags_and_audio_info(library: Path) -> None:
    raw = read_tags(library / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3")

    assert raw.tags["artist"] == "Carbon Leaf"
    assert raw.tags["tracknumber"] == "1/12"
    assert raw.duration_seconds == pytest.approx(1.0, abs=0.2)
    assert raw.bitrate_kbps == 32


def test_reads_m4a_tags(library: Path) -> None:
    raw = read_tags(library / "Jay-Z" / "The Blueprint" / "02 Takeover.m4a")

    assert raw.tags["title"] == "Takeover"


def test_untagged_file_returns_empty_tags(library: Path) -> None:
    raw = read_tags(library / "01 Billie Jean.MP3")

    assert raw.tags == {}


def test_empty_file_raises_tag_read_error(library: Path) -> None:
    with pytest.raises(TagReadError):
        read_tags(library / "broken.mp3")


def test_unrecognised_format_raises_tag_read_error(library: Path) -> None:
    with pytest.raises(TagReadError, match="unrecognised"):
        read_tags(library / "cover.jpg")


def test_reader_never_modifies_file(library: Path) -> None:
    path = library / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3"
    before = (path.read_bytes(), path.stat().st_mtime_ns)

    read_tags(path)

    assert (path.read_bytes(), path.stat().st_mtime_ns) == before


def test_missing_tag_block_and_zero_bitrate_are_handled() -> None:
    from organize_music.tag_reader import _bitrate_kbps, _first_values

    assert _first_values(None) == {}
    assert _bitrate_kbps(0) is None
    assert _bitrate_kbps(None) is None


def test_read_all_tags_renders_multivalue_and_binary(library: Path) -> None:
    """Multi-value text frames join with '; '; binary frames (album art) summarise size."""
    from mutagen.id3 import APIC, ID3, TPE1

    path = library / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3"
    tags = ID3(path)
    tags.add(TPE1(encoding=3, text=["Carbon Leaf", "Guest"]))
    tags.add(APIC(encoding=3, mime="image/png", type=3, desc="cover", data=b"\x89PNG\x00\x00"))
    tags.save(path)

    dump = read_all_tags(path)
    rendered = dict(dump.items)

    assert rendered["TPE1"] == "Carbon Leaf; Guest"
    assert rendered["APIC:cover"] == "<6 bytes>"


def test_read_all_tags_errors_and_unrecognised(library: Path) -> None:
    with pytest.raises(TagReadError):
        read_all_tags(library / "broken.mp3")
    with pytest.raises(TagReadError, match="unrecognised"):
        read_all_tags(library / "cover.jpg")


def test_scalar_renders_raw_bytes_and_plain_values() -> None:
    from types import SimpleNamespace

    from organize_music.tag_reader import _render_value, _scalar

    assert _scalar(b"1234") == "<4 bytes>"
    assert _scalar(42) == "42"
    assert _render_value(["x", "y"]) == "x; y"
    assert _render_value(SimpleNamespace(text="plain")) == "plain"  # frame with string .text

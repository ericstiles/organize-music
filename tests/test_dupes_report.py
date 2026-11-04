"""Tests for the pure duplicates report."""

from datetime import datetime
from pathlib import Path

from organize_music.dupes_report import DupesSummary, build_groups, render_duplicates_report

WHEN = datetime(2026, 11, 4, 9, 30)
MB = 1_000_000


def summary(**overrides: object) -> DupesSummary:
    sizes = {
        Path("Music2/Candlebox/01.mp3"): 5 * MB,
        Path("osx_sd_card_c_to_e/Candlebox/01.mp3"): 5 * MB,
        Path("ipod_favs/01.mp3"): 5 * MB,
        Path("Music2/Candlebox/02.mp3"): 3 * MB,
        Path("osx_sd_card_c_to_e/Candlebox/02.mp3"): 3 * MB,
        Path("loose | pipe.mp3"): 1 * MB,
        Path("Rock/loose | pipe.mp3"): 1 * MB,
    }
    hashes = {
        Path("Music2/Candlebox/01.mp3"): "aaa",
        Path("osx_sd_card_c_to_e/Candlebox/01.mp3"): "aaa",
        Path("ipod_favs/01.mp3"): "aaa",
        Path("Music2/Candlebox/02.mp3"): "bbb",
        Path("osx_sd_card_c_to_e/Candlebox/02.mp3"): "bbb",
        Path("loose | pipe.mp3"): "ccc",
        Path("Rock/loose | pipe.mp3"): "ccc",
    }
    fields: dict[str, object] = {
        "root": Path("/music"),
        "generated_at": WHEN,
        "candidates": 9,
        "groups": build_groups(hashes, sizes),
        "failures": (),
    }
    fields.update(overrides)
    return DupesSummary(**fields)  # type: ignore[arg-type]


def test_build_groups_sorted_by_reclaimable_space() -> None:
    groups = summary().groups

    assert [g.md5 for g in groups] == ["aaa", "bbb", "ccc"]
    assert groups[0].size == 5 * MB
    assert groups[0].reclaimable == 10 * MB
    assert groups[0].paths[0] == Path("Music2/Candlebox/01.mp3")


def test_header_states_report_only() -> None:
    text = render_duplicates_report(summary())

    assert text.startswith("# Duplicates Report\n")
    assert "2026-11-04 09:30" in text
    assert "Report only: no keeper is chosen and no files were moved." in text


def test_totals() -> None:
    text = render_duplicates_report(summary())

    assert "| Size-collision candidates hashed | 9 |" in text
    assert "| Groups of byte-identical files | 3 |" in text
    assert "| Files in those groups | 7 |" in text
    assert "| Extra copies (files beyond one per group) | 4 |" in text
    assert "| Reclaimable space | 0.01 GB |" in text


def test_overlap_counts_groups_per_pair_of_top_level_folders() -> None:
    text = render_duplicates_report(summary())

    # aaa spans Music2, ipod_favs, osx_sd_card_c_to_e; bbb spans Music2, osx_sd_card_c_to_e.
    assert "| `Music2` ↔ `osx_sd_card_c_to_e` | 2 |" in text
    assert "| `Music2` ↔ `ipod_favs` | 1 |" in text
    assert "| `ipod_favs` ↔ `osx_sd_card_c_to_e` | 1 |" in text
    assert "| `(library root)` ↔ `Rock` | 1 |" in text
    assert text.index("| `Music2` ↔ `osx_sd_card_c_to_e` | 2 |") < text.index("| 1 |")


def test_group_listing_shows_every_path_escaped() -> None:
    text = render_duplicates_report(summary())

    assert "### 1. 3 copies × 5.0 MB (md5 `aaa`)" in text
    assert "- `ipod_favs/01.mp3`" in text
    assert "- `loose \\| pipe.mp3`" in text


def test_group_listing_is_capped(monkeypatch: object) -> None:
    import organize_music.dupes_report as module

    original = module.GROUP_LIMIT
    module.GROUP_LIMIT = 1
    try:
        text = render_duplicates_report(summary())
    finally:
        module.GROUP_LIMIT = original

    assert "### 1. 3 copies" in text
    assert "### 2." not in text
    assert "Showing the largest 1 of 3 groups." in text


def test_failures_listed_and_empty_report() -> None:
    failed = summary(failures=((Path("bad.mp3"), "PermissionError: denied"),))
    empty = summary(groups=(), candidates=0)

    assert "| `bad.mp3` | PermissionError: denied |" in render_duplicates_report(failed)
    text = render_duplicates_report(empty)
    assert "| Groups of byte-identical files | 0 |" in text
    assert text.count("_None._") == 3

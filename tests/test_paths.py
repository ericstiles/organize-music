"""Tests for paths.py: safe relative paths and exFAT collision keys.

Pure module (no fsops). ``validate_relative`` rejects every escape attempt
(absolute, traversal, empty/NUL/control, oversize), ``path_key`` normalises
for case-insensitive collision detection on exFAT, and ``resolve_target``
joins under a root while refusing symlinks and canonical escapes. Table-driven
for the rejects, with 100% branch coverage on ``organize_music.paths``.
"""

from pathlib import PurePosixPath

import pytest

from organize_music import paths
from organize_music.paths import (
    MAX_PATH,
    MAX_SEGMENT,
    InvalidPath,
    is_case_only,
    path_key,
    resolve_target,
    validate_relative,
)

# --- constants --------------------------------------------------------------


def test_constants():
    assert MAX_SEGMENT == 120
    assert MAX_PATH == 400


# --- path_key ---------------------------------------------------------------


def test_path_key_case_insensitive():
    assert path_key("A/B.mp3") == path_key("a/b.MP3")


def test_path_key_nfc_normalised():
    # 'e' + combining acute (NFD) collapses to 'é' (NFC) before casefold.
    nfd = "e\u0301"
    assert path_key(nfd) == path_key("\u00e9")
    assert path_key(nfd) == "\u00e9".casefold()


# --- validate_relative ------------------------------------------------------


def test_validate_accepts_plain_relative():
    result = validate_relative("artist/album/01 Song.mp3")
    assert isinstance(result, PurePosixPath)
    assert str(result) == "artist/album/01 Song.mp3"


def test_validate_normalises_nfc():
    # NFD 'e' + combining acute -> NFC 'é' in the returned path.
    result = validate_relative("e\u0301")
    assert str(result) == "\u00e9"
    assert result == PurePosixPath("\u00e9")


def test_validate_rejects_invalid():
    bad = [
        "/abs",
        "../x",
        "a/../b",
        "a//b",
        "",
        "a\x00b",
        "a" * (MAX_SEGMENT + 1),
        "a" * (MAX_PATH + 1),
        ".",
        "..",
    ]
    for value in bad:
        with pytest.raises(InvalidPath):
            validate_relative(value)


def test_validate_rejects_control_chars():
    for value in ("a\x1fb", "a\x7fb", "ab\x07c"):
        with pytest.raises(InvalidPath):
            validate_relative(value)


def test_validate_rejects_total_over_max_each_segment_ok():
    # Four 120-char segments: each <= MAX_SEGMENT, but the total > MAX_PATH.
    seg = "a" * MAX_SEGMENT
    value = "/".join([seg, seg, seg, seg])
    assert len(value) > MAX_PATH
    with pytest.raises(InvalidPath):
        validate_relative(value)


def test_validate_rejects_non_string():
    with pytest.raises(InvalidPath):
        validate_relative(None)  # type: ignore[arg-type]
    with pytest.raises(InvalidPath):
        validate_relative(123)  # type: ignore[arg-type]


# --- resolve_target ---------------------------------------------------------


def test_resolve_returns_joined_inside_root(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "sub").mkdir()
    target = resolve_target(root, "sub/track.mp3")
    assert target == root / "sub" / "track.mp3"


def test_resolve_single_segment(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    target = resolve_target(root, "track.mp3")
    assert target == root / "track.mp3"


def test_resolve_missing_intermediate_is_allowed(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    # 'nothere' does not exist yet; the lstat walk skips it and the realpath
    # backstop confirms the canonical target stays inside the root.
    target = resolve_target(root, "nothere/track.mp3")
    assert target == root / "nothere" / "track.mp3"


def test_resolve_rejects_invalid_rel(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(InvalidPath):
        resolve_target(root, "../escape")


def test_resolve_rejects_symlink_dir_pointing_outside(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside)
    # The symlink is an intermediate component the path travels *through*.
    with pytest.raises(InvalidPath):
        resolve_target(root, "link/secret.mp3")


def test_resolve_rejects_symlink_final_component_outside(tmp_path):
    # A symlink as the *final* component that points outside the root has no
    # intermediate to lstat, so the realpath backstop catches it.
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(InvalidPath):
        resolve_target(root, "link")


# --- is_case_only -----------------------------------------------------------


def test_is_case_only_true():
    assert is_case_only("A/B.mp3", "a/b.MP3") is True


def test_is_case_only_false_same_string():
    assert is_case_only("a/b.mp3", "a/b.mp3") is False


def test_is_case_only_false_different_keys():
    assert is_case_only("a.mp3", "b.mp3") is False


# --- the containment helper, exercised directly to cover its branches -------


def test_is_within_helper():
    # _is_within(path, root): True when path equals or sits inside root.
    assert paths._is_within("/a", "/a") is True
    assert paths._is_within("/a/b", "/a") is True
    assert paths._is_within("/ab", "/a") is False
    assert paths._is_within("/x", "/a") is False

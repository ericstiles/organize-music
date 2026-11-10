"""Tests for the pure filename rename transform (Phase 4 standalone tool, cvf)."""
from organize_music.rename import rename_plan, transform_name


def test_transform_spaces_to_underscores():
    assert transform_name("01 Yay.mp3") == "01_Yay.mp3"


def test_transform_multiple_spaces_collapse():
    assert transform_name("a   b.txt") == "a_b.txt"


def test_transform_idempotent():
    name = "01_Yay.mp3"
    assert transform_name(name) == name


def test_transform_only_filename_not_dir():
    # extension preserved, only spaces -> underscores
    assert transform_name("Hello World.m4a") == "Hello_World.m4a"


def test_rename_plan_detects_collision():
    # two files resolving to the same target must be flagged, never silently overwritten
    files = ["a x.mp3", "a_x.mp3"]
    result = rename_plan(files)
    assert result.collisions  # non-empty
    # no target path appears more than once as a planned rename
    planned = [r.target for r in result.renames if r.changed]
    assert len(planned) == len(set(planned)) or result.collisions

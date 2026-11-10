"""Tests for CLI 'rename' command (cvf)."""
import os
from pathlib import Path

import pytest

from organize_music import cli


def test_rename_dry_run(library: Path, tmp_path: Path) -> None:
    """Dry-run default; no changes."""
    # Create a file with spaces in the name
    src = library / "01 File With Spaces.mp3"
    src.write_text("fake audio")
    
    # Run rename command (dry-run by default)
    args = ["rename", str(library), "--report", str(tmp_path / "r.md")]
    assert cli.main(args) == 0
    
    # Verify no changes made
    assert src.exists()
    assert not (library / "01_File_With_Spaces.mp3").exists()


def test_rename_apply(library: Path, tmp_path: Path) -> None:
    """--apply flag actually renames files."""
    # Create a file with spaces in the name
    src = library / "01 File With Spaces.mp3"
    src.write_text("fake audio")
    
    # Run rename command with --apply
    args = ["rename", str(library), "--apply", "--report", str(tmp_path / "r.md")]
    assert cli.main(args) == 0
    
    # Verify the file was renamed
    assert not src.exists()
    assert (library / "01_File_With_Spaces.mp3").exists()

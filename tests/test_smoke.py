"""Smoke test to verify that the verification harness and test runner are functional."""

import sys


def test_harness_environment() -> None:
    """Verify runtime environment meets minimum Python requirements."""
    assert sys.version_info >= (3, 12), f"Expected Python >= 3.12, got {sys.version}"


def test_smoke_assertion() -> None:
    """Basic deterministic smoke test."""
    test_data = {"artist": "Test Artist", "album": "Test Album", "track": "01 - Intro.mp3"}
    assert test_data["artist"] == "Test Artist"
    assert test_data["album"] == "Test Album"
    assert len(test_data) == 3


def test_package_import() -> None:
    """Verify package import and version availability."""
    import organize_music

    assert organize_music.__version__ == "0.1.0"

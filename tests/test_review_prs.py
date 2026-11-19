"""Tests for the PR reviewer agent's pure logic (tools/pr_review)."""

import pytest

from tools.pr_review.findings import new_failures, new_ruff_findings, new_unformatted
from tools.pr_review.meta import BeadMismatch, resolve_bead

BODY = "Fixes things.\n\nBead: organize_music-6ut.4\n"
TITLE = "fix(organize_music-6ut.4): sanitise each path segment"


def test_bead_id_agrees_across_branch_title_body() -> None:
    assert resolve_bead("bd/organize_music-6ut.4", TITLE, BODY) == "organize_music-6ut.4"


def test_bead_id_accepts_breaking_change_marker_in_title() -> None:
    title = "feat(organize_music-r3c)!: reviewer agent"
    body = "Bead: organize_music-r3c"
    assert resolve_bead("bd/organize_music-r3c", title, body) == "organize_music-r3c"


@pytest.mark.parametrize(
    ("branch", "title", "body", "reason"),
    [
        ("feature/x", TITLE, BODY, "branch"),
        ("bd/organize_music-6ut.5", TITLE, BODY, "disagree"),
        ("bd/organize_music-6ut.4", "fix: no id here", BODY, "title"),
        ("bd/organize_music-6ut.4", TITLE, "no bead line", "body"),
        ("bd/organize_music-6ut.4", TITLE, "Bead: organize_music-6ut.9", "disagree"),
    ],
)
def test_bead_id_mismatch_is_rejected(branch: str, title: str, body: str, reason: str) -> None:
    with pytest.raises(BeadMismatch, match=reason):
        resolve_bead(branch, title, body)


MAIN_RUFF = """\
src/organize_music/naming.py:3:1: I001 [*] Import block is un-sorted or un-formatted
tests/test_naming.py:26:101: E501 Line too long (118 > 100)
Found 2 errors.
"""


def test_new_ruff_findings_only() -> None:
    # The same finding on a shifted line is not new; a new code or file is.
    pr = """\
src/organize_music/naming.py:5:1: I001 [*] Import block is un-sorted or un-formatted
tests/test_naming.py:26:101: E501 Line too long (118 > 100)
src/organize_music/cli.py:10:5: F401 [*] `os` imported but unused
Found 3 errors.
"""
    assert new_ruff_findings(MAIN_RUFF, pr) == [
        "src/organize_music/cli.py:10:5: F401 [*] `os` imported but unused"
    ]


def test_new_ruff_findings_counts_duplicates() -> None:
    line = "tests/test_naming.py:40:101: E501 Line too long (118 > 100)"
    assert new_ruff_findings(MAIN_RUFF, MAIN_RUFF + line + "\n") == [line]


def test_fixed_ruff_findings_are_not_reported() -> None:
    assert new_ruff_findings(MAIN_RUFF, "All checks passed!\n") == []


def test_new_failures_only() -> None:
    main = "FAILED tests/test_a.py::test_old - AssertionError\n1 failed, 9 passed\n"
    pr = (
        "FAILED tests/test_a.py::test_old - AssertionError\n"
        "FAILED tests/test_b.py::test_new[x] - NameError: y\n"
        "ERROR tests/test_c.py - ImportError\n"
        "2 failed, 1 error, 8 passed\n"
    )
    assert new_failures(main, pr) == ["tests/test_b.py::test_new[x]", "tests/test_c.py"]


def test_new_unformatted_only() -> None:
    main = "Would reformat: tests/test_naming.py\n1 file would be reformatted\n"
    pr = "Would reformat: tests/test_naming.py\nWould reformat: src/x.py\n"
    assert new_unformatted(main, pr) == ["src/x.py"]


def test_new_unformatted_concise_output() -> None:
    # ruff >= 0.15 with --output-format concise
    main = "tests/test_naming.py:2:1: unformatted: File would be reformatted\n"
    pr = (
        main
        + "src/x.py:2:1: unformatted: File would be reformatted\n2 files would be reformatted\n"
    )
    assert new_unformatted(main, pr) == ["src/x.py"]

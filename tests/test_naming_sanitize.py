"""Tests for sanitising in naming.py (Phase 2)."""

import pytest

from organize_music.naming import sanitize


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("hello world", "hello_world"),
        ("a  b\tc", "a_b_c"),
        ("AC/DC", "AC_DC"),
        ('a:b*c?d"e<f>g|h', "a_b_c_d_e_f_g_h"),
        ("a__b___c", "a_b_c"),
        ("_leading_and_trailing_", "leading_and_trailing"),
        ("  spaced  ", "spaced"),
        ("a.b.", "a.b"),  # trailing dot stripped
        ("", ""),
    ],
)
def test_sanitize(raw, expected):
    assert sanitize(raw) == expected


def test_sanitize_missing_none():
    assert sanitize(None) == ""

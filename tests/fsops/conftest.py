"""Fixtures for the filesystem-primitive tests.

Honours the ``OM_FS_TEST_DIR`` environment variable: when it is set the whole
suite runs inside a fresh subdirectory of that path instead of pytest's
per-test ``tmp_path``.  This is how the same suite is pointed at the Pi's exFAT
mount in Phase 1 (§15 of ``docs/WEB_UI_PLAN.md``): the mount cannot host
pytest's default temp files the way a local tmpfs can, so the operator sets
``OM_FS_TEST_DIR`` to a directory *on* the exFAT volume and the primitives are
exercised against real exFAT behaviour.
"""

import os
import shutil
from pathlib import Path

import pytest

_counter = 0


@pytest.fixture()
def fs_dir(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """A fresh, empty directory for each test.

    When ``OM_FS_TEST_DIR`` is set the directory is created as a unique child
    of that path (used to run against the Pi's exFAT mount).  Otherwise it
    lives under pytest's ``tmp_path``.  The caller may create subdirectories;
    the directory itself is removed by pytest's ``tmp_path`` when no
    ``OM_FS_TEST_DIR`` is set, and left in place when it is (so the exFAT
    operator can inspect what the suite wrote).
    """
    global _counter
    base = os.environ.get("OM_FS_TEST_DIR")
    if base:
        _counter += 1
        root = Path(base)
        root.mkdir(parents=True, exist_ok=True)
        dest = root / f"fsops-{os.getpid()}-{_counter}"
        shutil.rmtree(dest, ignore_errors=True)
        dest.mkdir(parents=True)
        return dest
    dest = tmp_path / "fs"
    dest.mkdir()
    return dest

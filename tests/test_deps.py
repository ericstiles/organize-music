"""Regression tests for the early dependency check (organize_music-216).

The host .venv can silently drift out of sync with pyproject.toml: when a
declared dependency is missing, pytest only reports the import error for the one
test module that first imports it, which is easy to miss. The check below turns
that into a loud, early, well-formed failure *before* any test runs.
"""

import sys
from pathlib import Path

import pytest

from organize_music import deps


def test_missing_imports_returns_empty_when_everything_is_present() -> None:
    # In a correctly-synced environment the default REQUIRED list is fully importable.
    assert deps.missing_imports() == []


def test_missing_imports_reports_an_unimportable_module() -> None:
    required = [("bogus-dist", "no_such_module_xyz_12345")]
    assert deps.missing_imports(required) == ["no_such_module_xyz_12345"]


def test_missing_imports_ignores_importable_modules() -> None:
    # 'json' is always importable; it must not be reported as missing.
    assert deps.missing_imports([("stdlib-json", "json")]) == []


def test_missing_imports_reports_only_the_missing_ones_and_keeps_order() -> None:
    required = [
        ("ok-a", "json"),  # importable
        ("bad-b", "no_such_module_abc"),
        ("ok-c", "sys"),  # importable
        ("bad-d", "no_such_module_def"),
    ]
    assert deps.missing_imports(required) == [
        "no_such_module_abc",
        "no_such_module_def",
    ]


def test_ensure_dependencies_passes_when_all_present() -> None:
    # Should not raise in a synced environment.
    deps.ensure_dependencies()


def test_ensure_dependencies_raises_with_a_clear_message_when_missing() -> None:
    with pytest.raises(deps.DependenciesNotInstalled) as exc:
        deps.ensure_dependencies([("bogus-dist", "no_such_module_xyz_12345")])
    message = str(exc.value)
    # The message must name the missing module and point at the install command.
    assert "no_such_module_xyz_12345" in message
    assert "pip install" in message


def test_required_covers_every_declared_dependency() -> None:
    # The distribution names in pyproject.toml must all be represented, so the
    # check can never silently skip a declared dependency.
    declared = {
        "mutagen",
        "pyyaml",
        "fastapi",
        "uvicorn",
        "jinja2",
        "python-multipart",
        "itsdangerous",
        "mediafile",
        "yoyo-migrations",
    }
    dev = {
        "pytest",
        "ruff",
        "pytest-cov",
        "httpx",
    }
    dists = {dist for dist, _mod in deps.REQUIRED}
    assert declared <= dists, f"runtime deps missing from REQUIRED: {declared - dists}"
    assert dev <= dists, f"dev deps missing from REQUIRED: {dev - dists}"


def test_distribution_to_import_mapping_is_correct() -> None:
    # The tricky dist -> import-name mappings that caused the original confusion.
    by_dist = {dist: mod for dist, mod in deps.REQUIRED}
    assert by_dist["pyyaml"] == "yaml"
    assert by_dist["python-multipart"] == "multipart"
    assert by_dist["yoyo-migrations"] == "yoyo"
    assert by_dist["pytest-cov"] == "pytest_cov"


def test_root_conftest_fails_early_before_any_test_runs(tmp_path: Path, monkeypatch) -> None:
    """A root conftest that runs the check must abort the whole suite when a
    required module is missing, *before* the test bodies execute."""
    import subprocess

    conf = tmp_path / "conftest.py"
    conf.write_text(
        "from organize_music.deps import ensure_dependencies\n\n"
        "ensure_dependencies([('bogus-dist', 'no_such_module_xyz_9999')])\n",
        encoding="utf-8",
    )
    (tmp_path / "test_dummy.py").write_text(
        "def test_should_never_run():\n    assert True\n",
        encoding="utf-8",
    )
    env = {
        "PATH": "/usr/bin:/bin",
        "PYTHONPATH": f"{Path.cwd() / 'src'}",
    }
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            "test_dummy.py",
        ],
        cwd=tmp_path,
        env={**__import__("os").environ, **env},
        capture_output=True,
        text=True,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode != 0, "suite should fail when a required module is missing"
    # The failure is the conftest import, which names the missing module and the
    # install command -- a clear message, not a bare ModuleNotFoundError.
    assert "no_such_module_xyz_9999" in combined
    assert "DependenciesNotInstalled" in combined or "pip install" in combined
    # Collection aborted on the conftest import, so the dummy test never ran.
    assert "no tests ran" in combined or "error" in combined.lower()
    assert "1 passed" not in combined and "1 failed" not in combined

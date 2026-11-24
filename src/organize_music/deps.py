"""Fail early when the environment is missing a declared dependency.

The host ``.venv`` can drift out of sync with ``pyproject.toml`` (a dependency
is declared but never installed). Until the bug behind organize_music-216 was
addressed, that only surfaced as a bare ``ModuleNotFoundError`` for the single
test module that first imported the missing package -- easy to miss, and it
looked like a test bug rather than an environment problem.

``ensure_dependencies`` (called from the root ``conftest.py`` before any test
runs) turns that silent failure into a loud, well-formed one that names every
missing module and the command that fixes it.
"""

from collections.abc import Sequence
from importlib import import_module
from typing import NamedTuple

#: A required dependency, as (distribution name, import name).
Required = tuple[str, str]


class Dependency(NamedTuple):
    """A dependency as declared in pyproject.toml.

    ``dist`` is the distribution (package) name used on the pip command line;
    ``import_name`` is the top-level module name Python actually imports. The
    two differ for several packages (``pyyaml`` -> ``yaml``,
    ``python-multipart`` -> ``multipart``, ``yoyo-migrations`` -> ``yoyo``,
    ``pytest-cov`` -> ``pytest_cov``), which is why the mapping is explicit.
    """

    dist: str
    import_name: str


#: Every runtime and dev dependency declared in pyproject.toml, as
#: (distribution name, import name). The root conftest checks all of these so a
#: missing one can never be silently skipped.
REQUIRED: tuple[Dependency, ...] = (
    # [project].dependencies
    Dependency("mutagen", "mutagen"),
    Dependency("pyyaml", "yaml"),
    Dependency("fastapi", "fastapi"),
    Dependency("uvicorn", "uvicorn"),
    Dependency("jinja2", "jinja2"),
    Dependency("python-multipart", "multipart"),
    Dependency("itsdangerous", "itsdangerous"),
    Dependency("mediafile", "mediafile"),
    Dependency("yoyo-migrations", "yoyo"),
    # [project.optional-dependencies].dev
    Dependency("pytest", "pytest"),
    Dependency("ruff", "ruff"),
    Dependency("pytest-cov", "pytest_cov"),
    Dependency("httpx", "httpx"),
)


class DependenciesNotInstalled(Exception):
    """Raised when one or more declared dependencies cannot be imported."""


def missing_imports(required: Sequence[Required] = REQUIRED) -> list[str]:
    """Return the import names of ``required`` that cannot be imported, in order.

    Each entry is the *import name* (what you would ``import``), not the pip
    distribution name, because that is the name that fails at import time and
    the one that belongs in the error message.
    """
    missing: list[str] = []
    for _dist, import_name in required:
        try:
            import_module(import_name)
        except ImportError:
            missing.append(import_name)
    return missing


def _message(missing: list[str]) -> str:
    lines = [
        "Declared dependency is not importable: " + ", ".join(missing),
        "",
        "The .venv is out of sync with pyproject.toml. Install the declared",
        "dependencies from the repository root:",
        "",
        "    .venv/bin/pip install -e '.[dev]'",
        "    .venv/bin/pip install -r requirements-dev.txt",
    ]
    return "\n".join(lines)


def ensure_dependencies(required: Sequence[Required] = REQUIRED) -> None:
    """Raise :class:`DependenciesNotInstalled` if any declared dep is missing.

    Called from the root ``conftest.py`` so the whole suite stops with a clear
    message *before* any test body runs, instead of failing late with a bare
    import error.
    """
    missing = missing_imports(required)
    if missing:
        raise DependenciesNotInstalled(_message(missing))

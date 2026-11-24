"""Root conftest: fail early when the .venv is out of sync with pyproject.toml.

Loaded by pytest before any test is collected, so a missing declared dependency
raises here with a clear message and the install command, instead of a late,
bare ``ModuleNotFoundError`` in one test module (organize_music-216).
"""

from organize_music.deps import ensure_dependencies

# Runs at collection time, before any test body executes.
ensure_dependencies()

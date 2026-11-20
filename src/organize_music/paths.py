"""Safe relative paths and exFAT collision keys for the web engine.

Requests carry file ids, never filesystem paths, but hand-typed targets and
pattern output must be joined under a library root and must never escape it.
``validate_relative`` rejects every escape attempt and returns an NFC-normalised
:class:`PurePosixPath`; ``resolve_target`` additionally walks the components that
already exist on disk with ``lstat`` to refuse symlinks and confirms the
canonical path stays inside the canonical root. ``path_key`` is the
case-insensitive key exFAT collisions are detected on. Pure except the
``lstat`` walk in ``resolve_target``.
"""

from __future__ import annotations

import os
import stat
import unicodedata
from pathlib import Path, PurePosixPath

MAX_SEGMENT = 120
MAX_PATH = 400


class InvalidPath(ValueError):
    """Raised when a relative path is not safe to join under a root."""


def path_key(rel: str) -> str:
    """The exFAT collision key: NFC-normalised, then casefolded."""
    return unicodedata.normalize("NFC", rel).casefold()


def _is_within(path: str, root: str) -> bool:
    """True when canonical ``path`` equals or sits inside canonical ``root``."""
    return path == root or path.startswith(root + os.sep)


def validate_relative(rel: str) -> PurePosixPath:
    """Reject every escape attempt; return an NFC-normalised relative path.

    Rejects a non-string, the empty string, an absolute path, a ``..`` or ``.``
    segment, an empty segment (a doubled slash), a NUL or control character, a
    segment longer than ``MAX_SEGMENT`` and a total longer than ``MAX_PATH``.
    The returned path is NFC-normalised.
    """
    if not isinstance(rel, str):
        raise InvalidPath("path must be a string")
    text = unicodedata.normalize("NFC", rel)
    if not text:
        raise InvalidPath("empty path")
    if os.path.isabs(text):
        raise InvalidPath(f"absolute path: {rel!r}")
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise InvalidPath(f"control character in path: {rel!r}")
    if len(text) > MAX_PATH:
        raise InvalidPath(f"path too long: {len(text)} > {MAX_PATH}")
    for segment in text.split("/"):
        if not segment or segment in (".", ".."):
            raise InvalidPath(f"bad segment in path: {rel!r}")
        if len(segment) > MAX_SEGMENT:
            raise InvalidPath(f"segment too long: {len(segment)} > {MAX_SEGMENT}")
    return PurePosixPath(text)


def _refuse_symlinks(root: Path, target: Path) -> None:
    """lstat each existing intermediate component of ``target``; no symlinks.

    The final component is left to the realpath backstop in
    :func:`resolve_target`. A component that does not exist yet is skipped: the
    backstop still confirms the resolved path stays inside the root.
    """
    current = root
    for segment in target.parts[len(root.parts) :][:-1]:
        current = current / segment
        try:
            st = os.lstat(current)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode):
            raise InvalidPath(f"symlink not allowed: {segment!r}")


def resolve_target(root: Path, rel: str) -> Path:
    """Join ``rel`` under ``root``; refuse symlinks and canonical escapes.

    Validates ``rel`` first, then joins it under ``root``. Each existing
    intermediate component is ``lstat``-ed and a symlink raises
    :class:`InvalidPath`; finally the canonical target must stay inside the
    canonical root (this also catches a symlink final component). Returns the
    joined, unresolved path.
    """
    relative = validate_relative(rel)
    target = root / relative
    _refuse_symlinks(root, target)
    if not _is_within(os.path.realpath(target), os.path.realpath(root)):
        raise InvalidPath(f"path escapes root: {rel!r}")
    return target


def is_case_only(a: str, b: str) -> bool:
    """True when ``a`` and ``b`` differ but share an exFAT collision key."""
    return a != b and path_key(a) == path_key(b)

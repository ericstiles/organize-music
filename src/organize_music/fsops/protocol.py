"""The injectable filesystem interface for the mutation engine (PLAN §6.1, P1-7).

:mod:`fsops.primitives` is the *only* module that touches the filesystem; this
module wraps those primitives behind an :class:`FsOps` protocol so the engine can
receive an injectable ``FsOps`` and crash tests can wrap it (PLAN §11).  A
:class:`RealFs` implements the protocol by delegating to the primitives, with no
per-instance state.

:func:`write_text_atomic` is the one replacing write the tool performs: it writes
a *report* path (always outside the library, see
``cli_commands._ensure_outside``) through a temporary sibling and an atomic
``os.replace``.  It lives here, in ``fsops/`` -- the sanctioned place for
filesystem mutation -- so the no-unsafe-calls scan (which excludes ``fsops/``)
leaves it untouched.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Protocol, runtime_checkable

from . import primitives

__all__ = ["FsOps", "RealFs", "write_text_atomic"]


@runtime_checkable
class FsOps(Protocol):
    """Injectable filesystem operations.

    Every method mirrors a primitive in :mod:`fsops.primitives` (same name, same
    parameters, same return).  A ``FsOps`` holds no state of its own: the
    crash-safe guarantees live in the primitives it delegates to.
    """

    def rename_noreplace(self, src: Path, dst: Path) -> None: ...

    def fsync_file(self, path: Path) -> None: ...

    def fsync_dir(self, path: Path) -> None: ...

    def mkdir_one(self, path: Path) -> None: ...

    def rmdir_if_empty(self, path: Path) -> bool: ...

    def copy_new(self, src: Path, dst: Path) -> None: ...

    def discard_temp(self, work_dir: Path, path: Path) -> None: ...

    def entry_exists(self, parent: Path, name: str) -> bool: ...

    def same_device(self, *paths: Path) -> bool: ...


class RealFs:
    """The real :class:`FsOps`: a stateless delegation to the primitives.

    Carries no instance state, so wrapping it for a crash test requires only
    forwarding calls -- nothing to keep in sync between the wrapper and the real
    filesystem.
    """

    def rename_noreplace(self, src: Path, dst: Path) -> None:
        primitives.rename_noreplace(src, dst)

    def fsync_file(self, path: Path) -> None:
        primitives.fsync_file(path)

    def fsync_dir(self, path: Path) -> None:
        primitives.fsync_dir(path)

    def mkdir_one(self, path: Path) -> None:
        primitives.mkdir_one(path)

    def rmdir_if_empty(self, path: Path) -> bool:
        return primitives.rmdir_if_empty(path)

    def copy_new(self, src: Path, dst: Path) -> None:
        primitives.copy_new(src, dst)

    def discard_temp(self, work_dir: Path, path: Path) -> None:
        primitives.discard_temp(work_dir, path)

    def entry_exists(self, parent: Path, name: str) -> bool:
        return primitives.entry_exists(parent, name)

    def same_device(self, *paths: Path) -> bool:
        return primitives.same_device(*paths)


def write_text_atomic(path: Path, text: str) -> None:
    """Atomically write ``text`` (UTF-8) to ``path`` via a sibling temp file.

    The parent directory is created when missing.  The text first goes to
    ``<path>.tmp`` in the same directory and is then swapped into place with
    ``os.replace`` -- the one replacing write the tool does, and it is a report
    path, never a library file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)

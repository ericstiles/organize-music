"""Filesystem primitives for the mutation engine (PLAN §6).

The *only* place that touches the filesystem for mutations, so the invariants
here are the invariants the whole tool depends on: ``rename_noreplace`` never
replaces an existing file (no fallback to the replacing POSIX rename);
``copy_new`` creates its destination exclusively; and ``discard_temp`` unlinks
only a file owned by this operation under ``work_dir/tmp``.  No errno->app-code
mapping and no :class:`FsOps` protocol belong here (later phases).
"""

from __future__ import annotations

import ctypes
import errno
import os
import re
import sys
from pathlib import Path

__all__ = [
    "DestinationExists",
    "UnsupportedPlatform",
    "rename_noreplace",
    "fsync_file",
    "fsync_dir",
    "mkdir_one",
    "rmdir_if_empty",
    "copy_new",
    "discard_temp",
    "entry_exists",
    "same_device",
]


class DestinationExists(Exception):
    """The no-replace rename found the destination occupied; nothing moved."""


class UnsupportedPlatform(Exception):
    """The platform cannot perform an atomic no-replace rename."""


# Linux renameat2(2) / macOS renamex_np(2) flags.
AT_FDCWD = -100
RENAME_NOREPLACE = 1
RENAME_EXCL = 0x4


def _load_rename_lib() -> ctypes.CDLL:
    """Load the C library providing the atomic no-replace rename."""
    if sys.platform == "darwin":
        return ctypes.CDLL("libSystem.dylib", use_errno=True)
    return ctypes.CDLL("libc.so.6", use_errno=True)


# Resolved once at import time; tests may replace it to simulate a platform that
# lacks the symbol.
_LIB = _load_rename_lib()


def rename_noreplace(src: Path, dst: Path) -> None:
    """Atomically move ``src`` to ``dst`` without ever replacing ``dst``.

    Uses the platform's atomic no-replace rename.  An existing ``dst`` raises
    :class:`DestinationExists` and changes neither path; an unsupported platform
    (missing symbol, ``ENOSYS`` or ``EINVAL``) raises :class:`UnsupportedPlatform`
    and moves nothing.  There is no fallback to a replacing rename.
    """
    src_b = os.fsencode(src)
    dst_b = os.fsencode(dst)

    if sys.platform == "darwin":
        try:
            fn = _LIB.renamex_np
        except AttributeError:
            raise UnsupportedPlatform("renamex_np is unavailable on this platform") from None
        fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
        fn.restype = ctypes.c_int
        rc = fn(src_b, dst_b, RENAME_EXCL)
    else:
        try:
            fn = _LIB.renameat2
        except AttributeError:
            raise UnsupportedPlatform("renameat2 is unavailable on this platform") from None
        fn.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        fn.restype = ctypes.c_int
        rc = fn(AT_FDCWD, src_b, AT_FDCWD, dst_b, RENAME_NOREPLACE)

    if rc != 0:
        err = ctypes.get_errno()
        if err == errno.EEXIST:
            raise DestinationExists(f"destination already exists: {dst}")
        if err in (errno.EINVAL, errno.ENOSYS):
            raise UnsupportedPlatform(f"no-replace rename unsupported (errno {err})")
        raise OSError(err, os.strerror(err), os.fspath(dst))
    return None


def fsync_file(path: Path) -> None:
    """Flush the contents of ``path`` to durable storage."""
    fd = os.open(os.fspath(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def fsync_dir(path: Path) -> None:
    """Flush the directory entry of ``path`` to durable storage."""
    fd = os.open(os.fspath(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def mkdir_one(path: Path) -> None:
    """Create a single directory; raise :class:`FileExistsError` if it exists."""
    os.mkdir(os.fspath(path))


def rmdir_if_empty(path: Path) -> bool:
    """Remove ``path`` with ``os.rmdir``; return ``True`` if it was removed.

    Returns ``False`` (leaving the directory) when it is not empty or already
    gone, as ``ENOTEMPTY``/``EEXIST`` indicate.
    """
    try:
        os.rmdir(os.fspath(path))
    except OSError as exc:
        if exc.errno in (errno.ENOTEMPTY, errno.EEXIST):
            return False
        raise
    return True


def copy_new(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` creating it exclusively, then fsync the result.

    ``dst`` is opened ``O_WRONLY|O_CREAT|O_EXCL`` so an existing destination
    raises :class:`FileExistsError` rather than being clobbered.
    """
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with open(os.fspath(src), "rb") as fsrc:
        fdst = os.open(os.fspath(dst), flags, 0o644)
        try:
            while chunk := fsrc.read(1024 * 1024):
                os.write(fdst, chunk)
            os.fsync(fdst)
        finally:
            os.close(fdst)


_TEMP_NAME = re.compile(r"^op-\d+\..*$")


def discard_temp(work_dir: Path, path: Path) -> None:
    """Unlink ``path`` only when it is a temp file owned by this operation.

    ``path`` must live directly in ``work_dir/tmp`` and its name must match
    ``op-<digits>.<anything>``; any other path raises :class:`ValueError` and is
    left untouched, so a library file can never be removed through this helper.
    """
    tmp_dir = Path(work_dir) / "tmp"
    candidate = Path(path)
    if candidate.resolve().parent != tmp_dir.resolve() or not _TEMP_NAME.match(candidate.name):
        raise ValueError(f"refusing to discard unrecognised temp path: {path}")
    candidate.unlink()


def entry_exists(parent: Path, name: str) -> bool:
    """Return ``True`` when ``name`` is an exact entry in ``parent``.

    Comparison uses the exact names from :func:`os.listdir`, so on a
    case-insensitive filesystem ``entry_exists(parent, 'A.mp3')`` is ``False``
    when only ``a.mp3`` is present.
    """
    try:
        entries = os.listdir(os.fspath(parent))
    except FileNotFoundError:
        return False
    return name in entries


def same_device(*paths: Path) -> bool:
    """Return ``True`` when every path lives on the same device (by ``st_dev``)."""
    if not paths:
        return True
    devices = {os.stat(os.fspath(p)).st_dev for p in paths}
    return len(devices) == 1

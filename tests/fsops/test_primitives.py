"""Tests for the filesystem primitives in :mod:`organize_music.fsops`.

These exercise the no-replace rename and the safe move helpers against a real
directory.  When ``OM_FS_TEST_DIR`` is set the suite runs inside that directory
(see ``conftest.py``) so the same tests run against the Pi's exFAT mount.
"""

import ctypes
import errno
import os
import types
from pathlib import Path

import pytest

from organize_music.fsops import primitives
from organize_music.fsops.primitives import (
    DestinationExists,
    UnsupportedPlatform,
    copy_new,
    discard_temp,
    entry_exists,
    fsync_dir,
    fsync_file,
    mkdir_one,
    rename_noreplace,
    rmdir_if_empty,
    same_device,
)


def _is_case_insensitive(base: Path) -> bool:
    """Detect a case-insensitive filesystem using a probe in a scratch subdir."""
    probe_dir = base / "_cs_probe"
    probe_dir.mkdir(exist_ok=True)
    (probe_dir / "caseprobe.txt").write_text("x")
    # os.path.exists honours case-insensitivity; os.listdir does not.
    return (probe_dir / "CaseProbe.TXT").exists()


# --------------------------------------------------------------------------- #
# rename_noreplace
# --------------------------------------------------------------------------- #


def test_rename_noreplace_moves_a_file(fs_dir: Path) -> None:
    src = fs_dir / "source.txt"
    dst = fs_dir / "dest.txt"
    src.write_text("payload")
    rename_noreplace(src, dst)
    assert not src.exists()
    assert dst.read_text() == "payload"


def test_rename_noreplace_destination_exists_leaves_both_untouched(
    fs_dir: Path,
) -> None:
    src = fs_dir / "source.txt"
    dst = fs_dir / "dest.txt"
    src.write_bytes(b"original-source-bytes")
    dst.write_bytes(b"original-dest-bytes")
    with pytest.raises(DestinationExists):
        rename_noreplace(src, dst)
    # Neither file changed on disk.
    assert src.read_bytes() == b"original-source-bytes"
    assert dst.read_bytes() == b"original-dest-bytes"
    # os.listdir order is filesystem-dependent, so compare as a set.
    assert set(os.listdir(fs_dir)) == {"dest.txt", "source.txt"}


def test_rename_noreplace_case_only_raises_on_case_insensitive(
    fs_dir: Path,
) -> None:
    d = fs_dir / "caseonly"
    d.mkdir()
    src = d / "a.mp3"
    dst = d / "A.mp3"
    src.write_text("data")
    if not _is_case_insensitive(fs_dir):
        pytest.skip("case-sensitive filesystem: 'a.mp3' and 'A.mp3' are distinct names")
    try:
        with pytest.raises(DestinationExists):
            rename_noreplace(src, dst)
    except UnsupportedPlatform:
        pytest.skip("this case-insensitive platform has no atomic no-replace rename")
    # The only on-disk entry is the original lowercase name.
    assert set(os.listdir(d)) == {"a.mp3"}
    assert src.read_text() == "data"


def test_rename_noreplace_missing_symbol_raises_unsupported_and_unmoved(
    fs_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = fs_dir / "keep.txt"
    dst = fs_dir / "moved.txt"
    src.write_text("keep-me")
    # A library object without the atomic-rename symbol stands in for a platform
    # that cannot honour no-replace.
    fake_lib = types.SimpleNamespace()
    monkeypatch.setattr(primitives, "_LIB", fake_lib)
    with pytest.raises(UnsupportedPlatform):
        rename_noreplace(src, dst)
    assert src.exists()
    assert not dst.exists()
    assert src.read_text() == "keep-me"


def _fake_rename_lib(calls: list[tuple[object, ...]], rc: int, err: int) -> types.SimpleNamespace:
    """Both platform symbols: record each call's arguments, set errno ``err``, return ``rc``."""

    def fn(*args: object) -> int:
        calls.append(args)
        ctypes.set_errno(err)
        return rc

    return types.SimpleNamespace(renamex_np=fn, renameat2=fn)


def test_rename_noreplace_refuses_existing_name_before_the_syscall(
    fs_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # On case-insensitive APFS, renamex_np(RENAME_EXCL) lets 'a.mp3' -> 'A.mp3' through (same
    # file), so the occupied name must be refused before the system call, on every platform.
    src = fs_dir / "source.txt"
    dst = fs_dir / "dest.txt"
    src.write_text("s")
    dst.write_text("d")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(primitives, "_LIB", _fake_rename_lib(calls, 0, 0))
    with pytest.raises(DestinationExists):
        rename_noreplace(src, dst)
    assert calls == []


def test_rename_noreplace_eexist_from_the_syscall_raises_destination_exists(
    fs_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A destination created after the check is still caught by the atomic no-replace flag.
    src = fs_dir / "source.txt"
    src.write_text("s")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(primitives, "_LIB", _fake_rename_lib(calls, -1, errno.EEXIST))
    with pytest.raises(DestinationExists):
        rename_noreplace(src, fs_dir / "late.txt")
    assert len(calls) == 1
    assert src.read_text() == "s"


def test_darwin_enotempty_maps_to_destination_exists(
    fs_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # macOS renamex_np(RENAME_EXCL) reports an occupied destination with ENOTEMPTY,
    # while Linux renameat2(RENAME_NOREPLACE) reports EEXIST; the mapping must cover
    # both so the no-replace contract holds on darwin.  The module's sys binding is
    # swapped to force the darwin branch, so the test is deterministic on any host.
    src = fs_dir / "source.txt"
    dst = fs_dir / "late.txt"
    src.write_text("s")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(primitives, "sys", types.SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(primitives, "_LIB", _fake_rename_lib(calls, -1, errno.ENOTEMPTY))
    with pytest.raises(DestinationExists):
        rename_noreplace(src, dst)
    # The darwin branch ran: renamex_np(src, dst, RENAME_EXCL) — three args.
    assert calls == [(os.fsencode(src), os.fsencode(dst), primitives.RENAME_EXCL)]
    assert src.read_text() == "s"


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_eexist_still_maps_to_destination_exists(
    fs_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
) -> None:
    # The EEXIST -> DestinationExists mapping is unchanged on both platform branches.
    src = fs_dir / "source.txt"
    dst = fs_dir / "late.txt"
    src.write_text("s")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(primitives, "sys", types.SimpleNamespace(platform=platform))
    monkeypatch.setattr(primitives, "_LIB", _fake_rename_lib(calls, -1, errno.EEXIST))
    with pytest.raises(DestinationExists):
        rename_noreplace(src, dst)
    assert len(calls) == 1
    assert src.read_text() == "s"


@pytest.mark.parametrize("platform", ["darwin", "linux"])
@pytest.mark.parametrize("err", [errno.EINVAL, errno.ENOSYS])
def test_einval_enosys_still_unsupported(
    fs_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str,
    err: int,
) -> None:
    # EINVAL and ENOSYS keep mapping to UnsupportedPlatform on both platform branches.
    src = fs_dir / "source.txt"
    dst = fs_dir / "late.txt"
    src.write_text("s")
    calls: list[tuple[object, ...]] = []
    monkeypatch.setattr(primitives, "sys", types.SimpleNamespace(platform=platform))
    monkeypatch.setattr(primitives, "_LIB", _fake_rename_lib(calls, -1, err))
    with pytest.raises(UnsupportedPlatform):
        rename_noreplace(src, dst)
    assert len(calls) == 1
    assert src.read_text() == "s"


def test_rename_noreplace_never_falls_back_to_os_rename(
    fs_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = fs_dir / "source.txt"
    dst = fs_dir / "dest.txt"
    src.write_text("x")

    def _boom(*_args, **_kwargs):  # pragma: no cover - must never be called
        raise AssertionError("fallback to a replacing rename is forbidden")

    monkeypatch.setattr(os, "rename", _boom)
    rename_noreplace(src, dst)
    assert not src.exists()
    assert dst.exists()


# --------------------------------------------------------------------------- #
# copy_new
# --------------------------------------------------------------------------- #


def test_copy_new_copies_and_fsyncs(fs_dir: Path) -> None:
    src = fs_dir / "in.bin"
    dst = fs_dir / "out.bin"
    src.write_bytes(b"abc" * 1000)
    copy_new(src, dst)
    # copy_new copies, it does not move: the source remains in place.
    assert src.read_bytes() == b"abc" * 1000
    assert dst.read_bytes() == b"abc" * 1000


def test_copy_new_refuses_existing_destination(fs_dir: Path) -> None:
    src = fs_dir / "in.bin"
    dst = fs_dir / "out.bin"
    src.write_bytes(b"new")
    dst.write_bytes(b"existing")
    with pytest.raises(FileExistsError):
        copy_new(src, dst)
    assert dst.read_bytes() == b"existing"
    assert src.read_bytes() == b"new"


# --------------------------------------------------------------------------- #
# discard_temp
# --------------------------------------------------------------------------- #


def test_discard_temp_removes_matching_op_file(fs_dir: Path) -> None:
    tmp = fs_dir / "tmp"
    tmp.mkdir()
    op = tmp / "op-42.mp3"
    op.write_bytes(b"temp")
    discard_temp(fs_dir, op)
    assert not op.exists()


def test_discard_temp_leaves_siblings(fs_dir: Path) -> None:
    tmp = fs_dir / "tmp"
    tmp.mkdir()
    op = tmp / "op-7.mp3"
    op.write_bytes(b"temp")
    other = tmp / "op-8.mp3"
    other.write_bytes(b"keep")
    discard_temp(fs_dir, op)
    assert not op.exists()
    assert other.read_bytes() == b"keep"


def test_discard_temp_refuses_outside_tmp(fs_dir: Path) -> None:
    victim = fs_dir / "library-file.mp3"
    victim.write_bytes(b"precious")
    with pytest.raises(ValueError):
        discard_temp(fs_dir, victim)
    assert victim.exists()
    assert victim.read_bytes() == b"precious"


def test_discard_temp_refuses_traversal_escape(fs_dir: Path) -> None:
    # A path that climbs out of work_dir/tmp back into the library root must be
    # refused: it resolves to fs_dir/secret.txt, whose parent is not fs_dir/tmp.
    secret = fs_dir / "secret.txt"
    secret.write_bytes(b"do-not-touch")
    with pytest.raises(ValueError):
        discard_temp(fs_dir, Path(fs_dir, "tmp", "..", "secret.txt"))
    assert secret.exists()
    assert secret.read_bytes() == b"do-not-touch"


@pytest.mark.parametrize("bad_name", ["foo.mp3", "op-abc.mp3", "op-.mp3", "op-123"])
def test_discard_temp_refuses_bad_name(fs_dir: Path, bad_name: str) -> None:
    tmp = fs_dir / "tmp"
    tmp.mkdir()
    bad = tmp / bad_name
    bad.write_bytes(b"x")
    with pytest.raises(ValueError):
        discard_temp(fs_dir, bad)
    assert bad.exists()


# --------------------------------------------------------------------------- #
# rmdir_if_empty
# --------------------------------------------------------------------------- #


def test_rmdir_if_empty_removes_empty_dir(fs_dir: Path) -> None:
    d = fs_dir / "empty"
    d.mkdir()
    assert rmdir_if_empty(d) is True
    assert not d.exists()


def test_rmdir_if_empty_leaves_nonempty_dir(fs_dir: Path) -> None:
    d = fs_dir / "full"
    d.mkdir()
    (d / "child").write_text("keep")
    assert rmdir_if_empty(d) is False
    assert d.exists()
    assert (d / "child").exists()


def test_rmdir_if_empty_missing_dir_raises(fs_dir: Path) -> None:
    missing = fs_dir / "nope"
    with pytest.raises(FileNotFoundError):
        rmdir_if_empty(missing)


# --------------------------------------------------------------------------- #
# mkdir_one
# --------------------------------------------------------------------------- #


def test_mkdir_one_creates_dir(fs_dir: Path) -> None:
    d = fs_dir / "new"
    mkdir_one(d)
    assert d.is_dir()


def test_mkdir_one_existing_raises(fs_dir: Path) -> None:
    d = fs_dir / "exists"
    d.mkdir()
    with pytest.raises(FileExistsError):
        mkdir_one(d)


# --------------------------------------------------------------------------- #
# fsync helpers
# --------------------------------------------------------------------------- #


def test_fsync_file_and_dir_succeed(fs_dir: Path) -> None:
    f = fs_dir / "f.txt"
    f.write_text("x")
    sub = fs_dir / "sub"
    sub.mkdir()
    fsync_file(f)
    fsync_dir(sub)
    assert f.read_text() == "x"
    assert sub.is_dir()


# --------------------------------------------------------------------------- #
# entry_exists
# --------------------------------------------------------------------------- #


def test_entry_exists_exact_name_only(fs_dir: Path) -> None:
    (fs_dir / "a.mp3").write_text("x")
    assert entry_exists(fs_dir, "a.mp3") is True
    # Exact string match, so the uppercase variant is not found.
    assert entry_exists(fs_dir, "A.mp3") is False
    assert entry_exists(fs_dir, "missing.mp3") is False


def test_entry_exists_missing_parent_is_false(fs_dir: Path) -> None:
    missing = fs_dir / "does-not-exist"
    assert entry_exists(missing, "anything") is False


# --------------------------------------------------------------------------- #
# same_device
# --------------------------------------------------------------------------- #


def test_same_device_true_for_same_dir(fs_dir: Path) -> None:
    a = fs_dir / "a.txt"
    b = fs_dir / "b.txt"
    a.write_text("1")
    b.write_text("2")
    assert same_device(a, b) is True


def test_same_device_true_for_single_and_empty() -> None:
    assert same_device() is True
    assert same_device(Path("/etc")) is True


def test_same_device_false_for_distinct_device(fs_dir: Path) -> None:
    a = fs_dir / "a.txt"
    a.write_text("1")
    # /proc exists on Linux but not on macOS; stat the candidate only when it is
    # present so the suite runs on every platform.
    candidate = Path("/proc")
    if not candidate.exists():
        pytest.skip("/proc is not available on this platform")
    if os.stat(a).st_dev == os.stat(candidate).st_dev:
        pytest.skip("no distinct device available to test against")
    assert same_device(a, candidate) is False

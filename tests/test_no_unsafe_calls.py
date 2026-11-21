"""Guard: no raw filesystem replace/delete call outside fsops/ (PLAN §6.1, P1-7).

The mutation engine may replace or delete a file *only* through the fsops
primitives (invariant I7: "Library files are never replaced or deleted").  A raw
call to ``os.rename``/``os.replace``/``os.remove``/``os.unlink``/
``shutil.move``/``shutil.rmtree`` or to ``Path.rename``/``Path.replace``/
``Path.unlink`` anywhere under ``src/organize_music`` other than ``fsops/`` is
therefore a regression.  This test greps the source tree for them and fails,
listing ``file:line`` for each, when one appears.

Sanctioned exceptions (each has a one-line reason, per the acceptance criterion
"list the exact allowed exceptions"):

* ``markdown.py`` escapes a pipe in a Markdown table cell with ``str.replace`` --
  a string operation, not a filesystem one.
* ``fsops/protocol.py``'s ``write_text_atomic`` performs the one replacing write
  the tool does -- an atomic ``os.replace`` of a *report* path that lives outside
  the library (``cli_commands._ensure_outside``).  It lives in ``fsops/`` and is
  therefore not scanned, but it is recorded here so the exception is explicit and
  reviewed.
"""

from __future__ import annotations

import re
from pathlib import Path

from organize_music import __file__ as package_file

SRC = Path(package_file).parent  # src/organize_music

# (regex, report label).  Ordered most-specific first so a line is reported once
# with its most specific label.
_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"os\.rename\("), "os.rename()"),
    (re.compile(r"os\.replace\("), "os.replace()"),
    (re.compile(r"os\.remove\("), "os.remove()"),
    (re.compile(r"os\.unlink\("), "os.unlink()"),
    (re.compile(r"shutil\.move\("), "shutil.move()"),
    (re.compile(r"shutil\.rmtree\("), "shutil.rmtree()"),
    (re.compile(r"\.rename\("), "Path.rename()"),
    (re.compile(r"\.replace\("), "Path.replace()/str.replace()"),
    (re.compile(r"\.unlink\("), "Path.unlink()"),
)

# A `.replace(` match is a string operation, not a filesystem one, when its
# receiver is a string literal:  "lit".replace(...)  or  'lit'.replace(...).
_STR_RECEIVER_MARKERS = (
    chr(34) + ".replace",  # ".replace  -> a double-quoted literal's .replace
    chr(39) + ".replace",  # '.replace  -> a single-quoted literal's .replace
)

# Exact, reviewed exceptions.  Entry: (path relative to SRC, report label,
# substring identifying the call on its line, why it is safe).
_ALLOWED: tuple[tuple[str, str, str, str], ...] = (
    (
        "markdown.py",
        "Path.replace()/str.replace()",
        '.replace("|"',
        "escape a pipe in a Markdown table cell: str.replace, not a filesystem op",
    ),
)

# The sanctioned os.replace for report paths lives in fsops/ (excluded from the
# scan) and is recorded here so the exception is explicit and reviewed:
#   fsops/protocol.py  write_text_atomic()  ->  os.replace(tmp, report_path)
# The report path is always outside the library (cli_commands._ensure_outside),
# so it can never replace or delete a library file.


def _is_string_replace(line: str) -> bool:
    """True when the line's ``.replace(`` belongs to a string-literal receiver."""
    return any(marker in line for marker in _STR_RECEIVER_MARKERS)


def _is_allowed(rel: str, label: str, line: str) -> bool:
    for path, want_label, substring, _reason in _ALLOWED:
        if path == rel and want_label == label and substring in line:
            return True
    return False


def _violations_in_file(path: Path) -> list[str]:
    rel = path.relative_to(SRC).as_posix()
    if rel.split("/", 1)[0] == "fsops":
        return []  # fsops/ is the sanctioned place for these calls
    out: list[str] = []
    for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        for pattern, label in _PATTERNS:
            if not pattern.search(line):
                continue
            if label == "Path.replace()/str.replace()" and _is_string_replace(line):
                continue
            if _is_allowed(rel, label, line):
                continue
            out.append(f"{rel}:{lineno}: {label}  ->  {line.strip()}")
            break  # one violation per line; the most-specific label wins
    return out


def _all_violations() -> list[str]:
    found: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        found.extend(_violations_in_file(path))
    return found


def test_no_unsafe_filesystem_calls_outside_fsops() -> None:
    violations = _all_violations()
    assert not violations, (
        "unsafe filesystem call(s) found outside fsops/ "
        "(replace/delete must go through the fsops primitives, PLAN §6.1):\n"
        + "\n".join(violations)
    )


def test_real_fs_satisfies_fsops_protocol() -> None:
    # Imported inside the function so the scan test runs even before
    # fsops/protocol.py exists (test-first: this assertion is the RED that the
    # protocol implementation turns green).
    from organize_music.fsops.protocol import FsOps, RealFs

    assert isinstance(RealFs(), FsOps)


def test_real_fs_delegates_to_the_primitives(tmp_path: Path) -> None:
    # RealFs is a stateless delegator: exercise every method against a real
    # directory so the protocol is proven, not merely isinstance-checked.
    from organize_music.fsops.protocol import RealFs

    fs = RealFs()
    d = tmp_path / "lib"
    fs.mkdir_one(d)
    assert fs.entry_exists(d, "lib") is False  # 'lib' is not a child of d
    assert fs.entry_exists(tmp_path, "lib") is True  # but 'lib' is a child of tmp_path

    src = d / "a.txt"
    dst = d / "b.txt"
    src.write_text("payload")
    fs.rename_noreplace(src, dst)
    assert not src.exists() and dst.read_text() == "payload"

    fs.copy_new(dst, d / "c.txt")
    assert (d / "c.txt").read_text() == "payload"
    assert dst.read_text() == "payload"  # copy_new does not move

    fs.fsync_file(d / "c.txt")
    fs.fsync_dir(d)
    assert fs.same_device(d, d / "c.txt") is True

    tmp = d / "tmp"
    tmp.mkdir()
    op = tmp / "op-7.mp3"
    op.write_bytes(b"temp")
    fs.discard_temp(d, op)
    assert not op.exists()

    empty = d / "empty"
    empty.mkdir()
    assert fs.rmdir_if_empty(empty) is True
    assert not empty.exists()

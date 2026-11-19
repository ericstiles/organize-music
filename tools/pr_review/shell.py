"""Run external commands (gh, bd, git, claude) without raising on a non-zero exit."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

TIMEOUT_EXIT = 124


@dataclass(frozen=True)
class Result:
    code: int
    out: str
    err: str

    @property
    def ok(self) -> bool:
        return self.code == 0


class Runner(Protocol):
    def __call__(
        self,
        cmd: Sequence[str],
        cwd: Path | None = None,
        env: Mapping[str, str] | None = None,
        timeout: float | None = None,
    ) -> Result: ...


class CommandError(RuntimeError):
    """A command the reviewer depends on failed."""


def run(
    cmd: Sequence[str],
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
) -> Result:
    """Run a command and capture its output; a timeout becomes exit code 124."""
    full_env = {**os.environ, **env} if env else None
    try:
        done = subprocess.run(
            list(cmd), cwd=cwd, env=full_env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        return Result(TIMEOUT_EXIT, out, f"timed out after {timeout}s")
    except FileNotFoundError as exc:
        return Result(127, "", f"command not found: {exc.filename}")
    return Result(done.returncode, done.stdout, done.stderr)


def must(result: Result, what: str) -> Result:
    """Raise CommandError with the command's stderr when it failed."""
    if not result.ok:
        raise CommandError(f"{what} failed ({result.code}): {result.err.strip()[:500]}")
    return result

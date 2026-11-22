"""Fault-injecting filesystem wrapper for the crash matrix (PLAN §11, P1-12).

Every mutation op is run against a :class:`FaultyFs` that mimics a power cut at
a chosen filesystem call, so the recovery path is proven at every step.  A
crash is modelled by :class:`SimulatedCrash`, which subclasses ``BaseException``
rather than ``Exception`` so that no ``except Exception`` in the engine can ever
swallow it (PLAN §6.1).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from organize_music.fsops.protocol import FsOps

__all__ = ["SimulatedCrash", "FaultyFs", "count_calls"]

# The FsOps method surface.  FaultyFs dispatches only these names; any other
# attribute access raises AttributeError so the wrapper looks like an ordinary
# object for introspection and protocol checks.
_FSMETHODS: frozenset[str] = frozenset(
    {
        "rename_noreplace",
        "fsync_file",
        "fsync_dir",
        "mkdir_one",
        "rmdir_if_empty",
        "copy_new",
        "discard_temp",
        "entry_exists",
        "same_device",
    }
)


class SimulatedCrash(BaseException):
    """A simulated power cut: a :class:`BaseException`, never an :class:`Exception`.

    Subclassing ``BaseException`` is the whole point: the engine's recovery and
    error handling catch ``Exception``, so a ``SimulatedCrash`` must escape every
    one of them and surface to the test harness instead.
    """


class FaultyFs:
    """An :class:`FsOps` that raises :class:`SimulatedCrash` at a chosen call.

    The wrapper forwards every call to ``inner`` and counts them in ``calls``.
    On call number ``crash_at`` it raises a :class:`SimulatedCrash`; with
    ``when='before'`` the crash happens *before* the inner is reached (so the
    disk action of that step is skipped), and with ``when='after'`` it happens
    *after* the inner returns (so the disk action is done but its durable state
    write is not -- the classic torn step).
    """

    def __init__(self, inner: FsOps, crash_at: int, when: Literal["before", "after"]) -> None:
        self.inner = inner
        self.crash_at = crash_at
        self.when = when
        self.calls: int = 0

    def __getattr__(self, name: str) -> Callable[..., object]:
        if name not in _FSMETHODS:
            raise AttributeError(name)

        def call(*args: object, **kwargs: object) -> object:
            self.calls += 1
            method = getattr(self.inner, name)
            if self.when == "before":
                if self.calls == self.crash_at:
                    raise SimulatedCrash(f"crash before the {self.crash_at}th fs call ({name})")
                return method(*args, **kwargs)
            result = method(*args, **kwargs)
            if self.calls == self.crash_at:
                raise SimulatedCrash(f"crash after the {self.crash_at}th fs call ({name})")
            return result

        return call


def count_calls(run: Callable[[FaultyFs], object], inner: FsOps) -> int:
    """Run ``run`` once against a counting wrapper and return the total calls.

    The wrapper is a :class:`FaultyFs` whose crash point is effectively never
    reached, so it simply forwards every call to ``inner`` while counting them.
    """
    wrapper = FaultyFs(inner, crash_at=10**9, when="after")
    run(wrapper)
    return wrapper.calls

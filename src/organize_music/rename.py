"""Pure filename rename transform: spaces -> underscores, idempotent, collision-safe.

Only the FILENAME is transformed (never the directory part). This is the pure
core of the `rename` subcommand; disk I/O lives in the CLI layer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_WHITESPACE = re.compile(r"\s+")


def transform_name(filename: str) -> str:
    """Replace every run of whitespace in a filename with a single underscore.

    Only the name (not any path/directory) is transformed. Idempotent: running
    it on an already-transformed name changes nothing.
    """
    return _WHITESPACE.sub("_", filename)


@dataclass(frozen=True)
class RenameAction:
    """One planned rename, with its original and target filenames."""

    source: str
    target: str
    changed: bool

    @property
    def is_collision(self) -> bool:
        return self.source == self.target and not self.changed


@dataclass(frozen=True)
class RenamePlan:
    """A full plan: every file's rename action, plus any collisions detected."""

    renames: tuple[RenameAction, ...]
    collisions: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return any(r.changed for r in self.renames)

    @property
    def has_collisions(self) -> bool:
        return bool(self.collisions)


def rename_plan(filenames: list[str]) -> RenamePlan:
    """Plan renames for a flat list of filenames, detecting target collisions.

    A collision is when two distinct source filenames resolve to the same target,
    or when a source already occupies a target another file resolves to. Collided
    files are left unchanged (never silently overwritten) and reported.
    """
    claimed: set[str] = set()
    renames: list[RenameAction] = []
    collisions: set[str] = set()

    for name in filenames:
        target = transform_name(name)
        # A collision: another source already claims this target, or this source
        # itself already occupies a target someone else resolves to.
        collision = (target in claimed and target != name) or (name in claimed and target != name)
        if collision:
            collisions.add(name)
            renames.append(RenameAction(source=name, target=name, changed=False))
            continue
        claimed.add(name)
        claimed.add(target)
        renames.append(RenameAction(source=name, target=target, changed=target != name))

    return RenamePlan(renames=tuple(renames), collisions=tuple(sorted(collisions)))

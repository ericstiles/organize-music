"""Identify the beads issue a Hermes PR belongs to (pure)."""

from __future__ import annotations

import re

BRANCH_PREFIX = "bd/"
_TITLE = re.compile(r"^\w+\(([^)\s]+)\)!?:")
_BODY = re.compile(r"^Bead:\s*(\S+)\s*$", re.MULTILINE)


class BeadMismatch(ValueError):
    """The branch, PR title and PR body do not name the same bead."""


def resolve_bead(branch: str, title: str, body: str) -> str:
    """Return the bead id when branch `bd/<id>`, title `type(<id>):` and `Bead: <id>` agree."""
    if not branch.startswith(BRANCH_PREFIX) or len(branch) == len(BRANCH_PREFIX):
        raise BeadMismatch(f"branch {branch!r} is not bd/<id>")
    from_branch = branch[len(BRANCH_PREFIX) :]
    title_match = _TITLE.match(title)
    if title_match is None:
        raise BeadMismatch(f"title {title!r} does not start with type(<id>):")
    body_match = _BODY.search(body)
    if body_match is None:
        raise BeadMismatch("body has no 'Bead: <id>' line")
    ids = {from_branch, title_match.group(1), body_match.group(1)}
    if len(ids) != 1:
        raise BeadMismatch(f"branch, title and body disagree: {sorted(ids)}")
    return from_branch

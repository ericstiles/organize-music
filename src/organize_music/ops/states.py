"""The operation states and the allowed transitions between them (PLAN §6.2/§6.3).

An operation moves only through the states below, and crash safety depends on
never skipping one: a transition that is not listed here is illegal and must
leave the row untouched. The table is ``(kind, from_state) -> {to_states}`` and
is keyed exactly as the plan specifies.
"""

from __future__ import annotations

# States that mean the operation is finished; no further transition is allowed.
TERMINAL = frozenset({"committed", "failed", "skipped", "needs_attention"})

# States that mean an operation is in flight; at most one may exist per file
# (enforced by the operations_one_active_per_file partial unique index).
ACTIVE = frozenset({"intent", "staged", "parked", "applied"})

# (kind, from) -> the to-states that transition() permits. Exactly the plan.
ALLOWED: dict[tuple[str, str], frozenset[str]] = {
    ("move", "planned"): frozenset({"intent", "failed", "skipped"}),
    ("move", "intent"): frozenset({"applied", "staged", "failed", "needs_attention"}),
    ("move", "staged"): frozenset({"applied", "needs_attention"}),
    ("move", "applied"): frozenset({"committed", "needs_attention"}),
    ("retag", "planned"): frozenset({"intent", "failed", "skipped"}),
    ("retag", "intent"): frozenset({"staged", "failed", "needs_attention"}),
    ("retag", "staged"): frozenset({"parked", "failed", "needs_attention"}),
    ("retag", "parked"): frozenset({"applied", "failed", "needs_attention"}),
    ("retag", "applied"): frozenset({"committed", "needs_attention"}),
}


def is_allowed(kind: str, from_state: str, to_state: str) -> bool:
    """True when ``transition`` may move a ``kind`` op from ``from_state`` to ``to_state``."""
    return to_state in ALLOWED.get((kind, from_state), frozenset())

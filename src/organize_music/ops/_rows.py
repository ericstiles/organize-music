"""Mirror records and the operations projection for the oplog (b8p.16).

Kept separate from :mod:`organize_music.ops.oplog_repo` so that module stays
under the repo's 200-line limit. ``record`` reads attributes off the passed
operation and does not construct one, so it has no runtime dependency back on
the module that defines :class:`Operation`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from organize_music.ops.oplog_repo import Operation

# The operations row columns a get() projects, in dataclass order.
SELECT = (
    "SELECT op_id, batch_id, file_id, unit_seq, step_seq, kind, state, "
    "expect_path, expect_size, expect_mtime_ns, expect_row_version, "
    "params_json, error_code FROM operations"
)


def record(
    op: Operation,
    to: str,
    params: Mapping[str, object],
    error_code: str | None,
    now: str,
) -> dict[str, object]:
    """Build the JSONL mirror record appended after a successful transition."""
    return {
        "op_id": op.op_id,
        "batch_id": op.batch_id,
        "file_id": op.file_id,
        "unit_seq": op.unit_seq,
        "step_seq": op.step_seq,
        "kind": op.kind,
        "from_state": op.state,
        "state": to,
        "params": dict(params),
        "error_code": error_code,
        "at": now,
    }

"""Side-effect boundary: whole-file MD5. Read-only.

MD5 is used for duplicate detection only (no adversary), and matches `md5sum`
so results can be checked by hand on the Pi.
"""

import hashlib
from pathlib import Path

CHUNK_SIZE = 1 << 20  # 1 MiB


class HashError(Exception):
    """A file could not be read for hashing."""


def md5_file(path: Path, chunk_size: int = CHUNK_SIZE) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(chunk_size):
                digest.update(chunk)
    except OSError as exc:
        raise HashError(f"{type(exc).__name__}: {exc}") from exc
    return digest.hexdigest()

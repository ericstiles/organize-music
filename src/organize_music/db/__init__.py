"""SQLite connections and the single-writer lock for library.db.

The writer owns library.db's only write connection (WAL, synchronous=FULL,
foreign_keys on) so the operation log commits durably; HTTP handlers open
query_only readers that read concurrently from the write-ahead log. An
exclusive ``WriterLock`` (an ``fcntl.flock`` on ``state/writer.lock``) keeps
the server and any CLI writer from touching library.db at the same time.
"""

from organize_music.db.connection import (
    WriterBusy,
    WriterLock,
    open_reader,
    open_writer,
)
from organize_music.db.migrations import SchemaTooNew, available, migrate

__all__ = [
    "WriterBusy",
    "WriterLock",
    "open_reader",
    "open_writer",
    "SchemaTooNew",
    "available",
    "migrate",
]

"""App factory for the library web UI (PLAN §9.1, issue b8p.29).

``create_app`` builds a FastAPI application over ``library.db``: a JSON
``/healthz`` probe, a redirect from ``/`` to ``/files``, and the paged
``/files`` list. Templates render with Jinja2 autoescape on; the vendored
htmx script is served from ``/static``. The app holds no write connection:
each request opens its own read-only connection to the database.
"""

from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from organize_music.config import Config
from organize_music.db.connection import open_reader
from organize_music.web import routes_files

# library.db lives beside the rest of the state (backups, the writer lock, ...).
_DB_NAME = "library.db"

_LOG = logging.getLogger(__name__)


def create_app(config: Config) -> FastAPI:
    """Build the library web app from a :class:`Config`."""
    app = FastAPI(title="organize-music")
    static_dir = Path(__file__).parent / "static"
    templates_dir = Path(__file__).parent / "templates"
    app.state.db_path = config.state_dir / _DB_NAME
    app.state.library_mount = config.library_mount
    app.state.templates = Jinja2Templates(directory=templates_dir)
    app.include_router(routes_files.router)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    app.add_api_route("/healthz", _healthz, methods=["GET"])
    return app


def _healthz(request: Request) -> JSONResponse:
    """``GET /healthz``: DB healthy, library mounted (no auth).

    ``ok`` is true only when every component is healthy: the database
    carries the migrated ``files`` table (``db``) and the library mount
    is a real mount point (``library_mounted``).
    """
    db_path: Path = request.app.state.db_path
    mount: Path = request.app.state.library_mount
    db = _db_ok(db_path)
    mounted = _library_mounted(mount)
    return JSONResponse(
        {
            "ok": db and mounted,
            "db": db,
            "library_mounted": mounted,
        }
    )


def _library_mounted(mount: Path) -> bool:
    """True when ``library_mount`` is a real mount point.

    ``library_mount`` must be configured as the mount point itself (the
    default config already does this). A subdirectory of the mount is never
    a mount point, and so is the empty folder that remains after the drive
    is unmounted or unplugged — so both report False, which is exactly the
    outage monitoring needs to see. A missing path also reports False
    (``os.path.ismount`` is False for paths that cannot be stat'ed).
    """
    return os.path.ismount(mount)


def _db_ok(db_path: Path) -> bool:
    """True when ``library.db`` exists, opens, and has a queryable ``files`` table.

    A missing file reports False. A present-but-corrupt file (not a valid
    database) reports False: the probe's query raises ``DatabaseError`` on
    a corrupt file. A zero-byte file or an unmigrated database opens fine
    but has no ``files`` table, and reports False: a schema-less database
    cannot serve any page (``/files`` fails with ``no such table: files``).
    A migrated database with an empty ``files`` table reports True. The
    check is read-only: the reader connection is ``query_only`` and the
    probe is a single ``SELECT``. If opening the file raises, the error is
    logged at warning level and the probe reports False.
    """
    if not db_path.is_file():
        return False
    conn: sqlite3.Connection | None = None
    try:
        conn = open_reader(db_path)
        conn.execute("SELECT 1 FROM files LIMIT 1").fetchone()
        return True
    except sqlite3.Error as exc:
        # Opening can fail too (unreadable file, I/O error, bad PRAGMA): log it
        # with the path and report db: false instead of a 500
        # (organize_music-8ct). The JSON carries no error details.
        _LOG.warning("healthz probe failed for %s: %s", db_path, exc)
        return False
    finally:
        if conn is not None:
            conn.close()

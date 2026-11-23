"""App factory for the library web UI (PLAN §9.1, issue b8p.29).

``create_app`` builds a FastAPI application over ``library.db``: a JSON
``/healthz`` probe, a redirect from ``/`` to ``/files``, and the paged
``/files`` list. Templates render with Jinja2 autoescape on; the vendored
htmx script is served from ``/static``. The app holds no write connection:
each request opens its own read-only connection to the database.
"""

from __future__ import annotations

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
    """``GET /healthz``: DB openable, library mounted, service up (no auth)."""
    db_path: Path = request.app.state.db_path
    mount: Path = request.app.state.library_mount
    return JSONResponse(
        {
            "ok": True,
            "db": _db_ok(db_path),
            "library_mounted": mount.exists(),
        }
    )


def _db_ok(db_path: Path) -> bool:
    """True when ``library.db`` exists and opens as a readable SQLite database.

    A missing file reports False. A present-but-corrupt file (not a valid
    database) reports False: ``SELECT 1`` is a constant that never touches the
    file, so the probe reads ``sqlite_master`` instead, which raises
    ``DatabaseError`` on a corrupt file. An empty file is a valid empty
    database and reports True.
    """
    if not db_path.is_file():
        return False
    conn = open_reader(db_path)
    try:
        conn.execute("SELECT name FROM sqlite_master LIMIT 1").fetchone()
        return True
    except sqlite3.DatabaseError:
        return False
    finally:
        conn.close()

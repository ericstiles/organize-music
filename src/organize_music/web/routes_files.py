"""Routes for the files list page (PLAN §9.2, issue b8p.29).

``GET /files`` returns one page (100 rows) of the ``files`` table, ordered by
``path_key`` then ``file_id`` so paging is deterministic at 100k rows (§9.5).
``GET /`` redirects to it. Each request opens its own read-only connection to
``library.db`` and closes it before the response is sent.

A read-only request must never create or change the database. When the database
is missing or its schema has not been applied yet, ``/files`` answers 503 with a
short "run the scan first" page instead of a 500 traceback (organize_music-8gz).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from starlette.responses import HTMLResponse

from organize_music.db.connection import open_reader
from organize_music.db.files_repo import FilesRepo

# 100 rows per page (PLAN §9.2 / §9.5).
PAGE_SIZE = 100

router = APIRouter()


def _reader(request: Request) -> Iterator[sqlite3.Connection | None]:
    """Yield a read-only connection to ``library.db`` for one request.

    The connection is opened for the duration of the handler and closed on exit,
    so a single worker never holds an open connection between requests.
    ``open_reader`` is read-only, so a missing database raises and is caught here
    rather than creating the file; the handler then renders the 503 page.
    """
    db_path: Path = request.app.state.db_path
    conn: sqlite3.Connection | None = None
    try:
        conn = open_reader(db_path)
    except sqlite3.Error:
        conn = None
    if conn is None:
        yield None
        return
    try:
        yield conn
    finally:
        conn.close()


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    """``GET /`` redirects to the files list."""
    return RedirectResponse(url="/files", status_code=307)


@router.get("/files")
def files(
    request: Request,
    page: int = Query(1, ge=1),
    conn: sqlite3.Connection | None = Depends(_reader),
) -> HTMLResponse:
    """``GET /files?page=N`` renders page ``N`` (1-based) of the files list."""
    if conn is None:
        # The database is missing: a read-only request must not create it.
        return _not_initialised(request)

    offset = (page - 1) * PAGE_SIZE
    repo = FilesRepo(conn)
    try:
        rows = repo.page(offset, PAGE_SIZE)
        total = repo.count()
    except sqlite3.OperationalError:
        # The file exists but the schema is not applied yet (a 0-byte file or a
        # partially migrated database): treat it as not initialised.
        return _not_initialised(request)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    template = request.app.state.templates
    return template.TemplateResponse(
        request,
        "files.html",
        {"rows": rows, "page": page, "pages": pages, "total": total},
    )


def _not_initialised(request: Request) -> HTMLResponse:
    """Render the 503 page shown before the library has been scanned."""
    template = request.app.state.templates
    return template.TemplateResponse(request, "not_initialised.html", status_code=503)

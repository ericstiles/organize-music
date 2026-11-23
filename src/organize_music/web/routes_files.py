"""Routes for the files list page (PLAN §9.2, issue b8p.29).

``GET /files`` returns one page (100 rows) of the ``files`` table, ordered by
``path_key`` then ``file_id`` so paging is deterministic at 100k rows (§9.5).
``GET /`` redirects to it. Each request opens its own read-only connection to
``library.db`` and closes it before the response is sent.
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


def _reader(request: Request) -> Iterator[sqlite3.Connection]:
    """Yield a read-only connection to ``library.db`` for one request.

    The connection is opened for the duration of the handler and closed on exit,
    so a single worker never holds an open connection between requests.
    """
    db_path: Path = request.app.state.db_path
    conn = open_reader(db_path)
    try:
        yield conn
    finally:
        conn.close()


@router.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    """``GET /`` redirects to the files list."""
    return RedirectResponse(url="/files", status_code=307)


@router.get("/files")
def files(request: Request, page: int = Query(1, ge=1), conn=Depends(_reader)) -> HTMLResponse:
    """``GET /files?page=N`` renders page ``N`` (1-based) of the files list."""
    offset = (page - 1) * PAGE_SIZE
    repo = FilesRepo(conn)
    rows = repo.page(offset, PAGE_SIZE)
    total = repo.count()
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    template = request.app.state.templates
    return template.TemplateResponse(
        request,
        "files.html",
        {"rows": rows, "page": page, "pages": pages, "total": total},
    )

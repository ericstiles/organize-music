"""Routes for the files list page (PLAN §9.2, issue b8p.29).

``GET /files`` returns one page (100 rows) of the ``files`` table, ordered by
``path_key`` then ``file_id`` so paging is deterministic at 100k rows (§9.5).
``GET /`` redirects to it. Each request opens its own read-only connection to
``library.db`` and closes it before the response is sent.

A read-only request must never create or change the database. When the database
is missing or its schema has not been applied yet, ``/files`` answers 503 with a
short "run the scan first" page instead of a 500 traceback (organize_music-8gz).

The page's rows and its total come from one read transaction, so they always
agree; a page number past the end redirects (303) to the last real page
(organize_music-hqd).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import RedirectResponse
from starlette.responses import HTMLResponse, Response

from organize_music.db.connection import open_reader
from organize_music.db.files_repo import FileRow, FilesRepo

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
) -> Response:
    """``GET /files?page=N`` renders page ``N`` (1-based) of the files list.

    A page number past the last page redirects (303) to the last page; an
    empty database (0 rows) renders page 1 of 1 instead, so no request ever
    bounces between empty pages.
    """
    if conn is None:
        # The database is missing: a read-only request must not create it.
        return _not_initialised(request)

    offset = (page - 1) * PAGE_SIZE
    repo = FilesRepo(conn)
    try:
        rows, total = _page_and_total(repo, conn, offset)
    except sqlite3.OperationalError:
        # The file exists but the schema is not applied yet (a 0-byte file or a
        # partially migrated database): treat it as not initialised.
        return _not_initialised(request)
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    if page > pages:
        return RedirectResponse(url=f"/files?page={pages}", status_code=303)
    template = request.app.state.templates
    return template.TemplateResponse(
        request,
        "files.html",
        {"rows": rows, "page": page, "pages": pages, "total": total},
    )


def _page_and_total(
    repo: FilesRepo, conn: sqlite3.Connection, offset: int
) -> tuple[list[FileRow], int]:
    """Return one page and the total row count, read in a single transaction.

    ``repo.page`` and ``repo.count`` run inside one explicit read transaction
    (BEGIN ... COMMIT, ROLLBACK on error) on the reader connection, so both
    reads share one SQLite snapshot (WAL gives a consistent read): the rows
    shown and "N files / page X of Y" can never disagree, even if a scan
    commits between them.
    """
    conn.execute("BEGIN")
    try:
        rows = repo.page(offset, PAGE_SIZE)
        total = repo.count()
    except BaseException:
        conn.rollback()
        raise
    conn.commit()
    return rows, total


def _not_initialised(request: Request) -> HTMLResponse:
    """Render the 503 page shown before the library has been scanned."""
    template = request.app.state.templates
    return template.TemplateResponse(request, "not_initialised.html", status_code=503)

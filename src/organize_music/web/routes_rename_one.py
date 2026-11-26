"""Rename one file from the UI: preview then confirm (PLAN §6.4, §9.4, b8p.30).

``GET /files/{file_id}/rename`` shows the file's current name in a form.
``POST /files/{file_id}/rename`` validates the hand-typed ``new_name`` (joined
under the row's folder, filename only) with ``paths.validate_relative`` and
stores a draft batch with one planned move op in ``state_dir/drafts.db``; it
changes nothing on disk and works while mutations are disabled (PLAN §9.4).
``POST /batches/{batch_id}/confirm`` (implemented in
:mod:`rename_confirm`) re-checks the row's ``row_version`` against the draft's
precondition, copies the batch and its op into ``library.db`` and runs
``run_move`` synchronously, rendering the result.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, Response

from organize_music.db.connection import open_reader
from organize_music.db.files_repo import FileRow, FilesRepo
from organize_music.paths import InvalidPath, validate_relative
from organize_music.web import drafts, rename_confirm

router = APIRouter()


def _utcnow() -> str:
    """A UTC timestamp for the draft rows."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _reader(request: Request) -> Iterator[sqlite3.Connection | None]:
    """A read-only connection to library.db for one request (None if missing)."""
    conn: sqlite3.Connection | None = None
    try:
        conn = open_reader(request.app.state.db_path)
    except sqlite3.Error:
        pass
    if conn is None:
        yield None
        return
    try:
        yield conn
    finally:
        conn.close()


def _basename(row: FileRow) -> str:
    path = row.path or row.last_path
    return path.rsplit("/", 1)[-1]


def _not_initialised(request: Request) -> HTMLResponse:
    template = request.app.state.templates
    return template.TemplateResponse(request, "not_initialised.html", status_code=503)


def _form_page(
    request: Request,
    row: FileRow | None,
    batch_id: int | None,
    proposed: str | None,
    error: dict[str, str] | None = None,
    status_code: int = 200,
) -> Response:
    """Render rename_one.html: the form, the preview, or an error for it."""
    template = request.app.state.templates
    context = {
        "row": row,
        "default_name": _basename(row) if row is not None else "",
        "draft_id": batch_id,
        "proposed": proposed,
        "error": error,
    }
    return template.TemplateResponse(request, "rename_one.html", context, status_code=status_code)


@router.get("/files/{file_id}/rename")
def rename_form(
    request: Request,
    file_id: int,
    conn: sqlite3.Connection | None = Depends(_reader),
) -> Response:
    """``GET /files/{file_id}/rename``: a form with the file's current name."""
    if conn is None:
        return _not_initialised(request)
    row = FilesRepo(conn).get(file_id)
    if row is None:
        return _form_page(
            request,
            None,
            None,
            None,
            {"code": "NOT_FOUND", "message": f"no file with id {file_id}"},
            status_code=404,
        )
    return _form_page(request, row, None, None)


@router.post("/files/{file_id}/rename")
def rename_preview(
    request: Request,
    file_id: int,
    new_name: str = Form(...),
    conn: sqlite3.Connection | None = Depends(_reader),
) -> Response:
    """``POST /files/{file_id}/rename``: validate, store a draft, preview.

    The draft goes to the scratch ``drafts.db`` (PLAN §6.4): nothing on disk
    changes, and the preview works while mutations are disabled (PLAN §9.4).
    """
    if conn is None:
        return _not_initialised(request)
    row = FilesRepo(conn).get(file_id)
    if row is None:
        return _form_page(
            request,
            None,
            None,
            None,
            {"code": "NOT_FOUND", "message": f"no file with id {file_id}"},
            status_code=404,
        )
    if row.status != "present" or row.path is None:
        return _form_page(
            request,
            row,
            None,
            None,
            {"code": "NOT_PRESENT", "message": "the file is not present; run the scan first"},
            status_code=422,
        )
    if "/" in new_name:
        # Filename only, same folder: a '/' would be a move to another folder,
        # which is out of scope for this tracer.
        return _form_page(
            request,
            row,
            None,
            None,
            {"code": "INVALID_NAME", "message": "filename only, same folder: no '/'"},
            status_code=422,
        )
    folder = row.path.rsplit("/", 1)[0] if "/" in row.path else ""
    joined = f"{folder}/{new_name}" if folder else new_name
    try:
        validate_relative(joined)
    except InvalidPath as exc:
        return _form_page(
            request, row, None, None, {"code": "INVALID_NAME", "message": str(exc)}, status_code=422
        )
    dconn = drafts.open_drafts(request.app.state.state_dir)
    try:
        batch_id = drafts.save_draft(
            dconn,
            new_name=new_name,
            file_id=row.file_id,
            src_rel=row.path,
            dst_rel=joined,
            size=row.size,
            mtime_ns=row.mtime_ns,
            row_version=row.row_version,
            now=_utcnow(),
        )
    finally:
        dconn.close()
    return _form_page(request, row, batch_id, joined)


@router.post("/batches/{batch_id}/confirm")
def confirm(request: Request, batch_id: int) -> Response:
    """``POST /batches/{batch_id}/confirm``: the confirm flow of rename_confirm."""
    return rename_confirm.confirm(request, batch_id)

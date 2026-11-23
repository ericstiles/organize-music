"""Web UI for the music library (FastAPI, PLAN §9).

The first layer is the app factory in :mod:`organize_music.web.app`, which wires
the files list and health probe in :mod:`organize_music.web.routes_files` over a
read-only connection to ``library.db``.
"""

from organize_music.web.app import create_app

__all__ = ["create_app"]

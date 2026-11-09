"""Pure naming: template + TrackMetadata -> proposed relative path (unsanitised interpolation)."""
from __future__ import annotations

import re
from pathlib import Path

from organize_music.models import TrackMetadata

_PLACEHOLDER = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _field_value(track: TrackMetadata, name: str) -> str:
    if name == "track_number":
        v = track.track_number.value
    elif name == "disc_number":
        v = track.disc_number.value
    elif name == "track":
        v = track.track_number.value
    elif name == "title":
        v = track.title.value
    elif name == "artist":
        v = track.artist.value
    elif name == "album":
        v = track.album.value
    elif name == "ext":
        return track.record.ext
    else:
        return ""
    if v is None:
        return ""
    return str(v)


def render_name(template: str, track: TrackMetadata) -> str:
    """Interpolate placeholders into a path string. No sanitising here."""
    def repl(match: re.Match[str]) -> str:
        return _field_value(track, match.group(1))
    return _PLACEHOLDER.sub(repl, template)

"""Pure naming: template + TrackMetadata -> a sanitised relative path."""

from __future__ import annotations

import re

from organize_music.models import TrackMetadata


def sanitize(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value)
    # spaces -> underscore
    text = re.sub(r"\s+", "_", text)
    # illegal chars -> underscore
    text = re.sub(r'[/\\:*?"<>|\x00-\x1f]', "_", text)
    # collapse repeated underscores
    text = re.sub(r"_+", "_", text)
    # strip leading/trailing _, ., spaces
    text = text.strip("_. ")
    return text


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
        return sanitize(track.record.ext)
    else:
        return ""
    if v is None:
        return ""
    # Sanitise the value before interpolation so that a '/' inside a tag value
    # (e.g. "AC/DC") becomes "AC_DC" instead of an extra path segment.
    return sanitize(str(v))


def render_name(template: str, track: TrackMetadata) -> str:
    """Interpolate placeholders and sanitise every path segment.

    Each path component is sanitised on its own so that a '/' inside a tag value
    never becomes an extra folder, a missing field leaves no empty folder, and
    the file extension on the last segment is preserved.
    """
    interpolated = _PLACEHOLDER.sub(lambda m: _field_value(track, m.group(1)), template)
    segments = interpolated.split("/")
    out: list[str] = []
    for segment in segments[:-1]:
        cleaned = sanitize(segment)
        if cleaned:
            out.append(cleaned)
    # The last segment carries the extension: sanitise the stem, keep the ext.
    last = segments[-1]
    dot = last.rfind(".")
    if dot != -1:
        stem, ext = last[:dot], last[dot + 1 :]
        cleaned = sanitize(stem)
        if cleaned:
            out.append(f"{cleaned}.{ext}")
    else:
        cleaned = sanitize(last)
        if cleaned:
            out.append(cleaned)
    return "/".join(out)


def detect_collisions(items: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """Given (proposed_path, md5) pairs, group proposals sharing a path.

    Returns a mapping of target path -> list of (source-ish, md5) for targets
    with more than one proposer. Empty dict when no collisions.
    """
    groups: dict[str, list[tuple[str, str]]] = {}
    for path, md5 in items:
        groups.setdefault(path, []).append((path, md5))
    return {p: g for p, g in groups.items() if len(g) > 1}

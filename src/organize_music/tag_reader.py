"""Side-effect boundary: the only module that imports mutagen. Read-only."""

from pathlib import Path

import mutagen

from organize_music.models import RawTagDump, RawTags


class TagReadError(Exception):
    """A file could not be parsed as audio."""


def _first_values(tags: mutagen.Tags | None) -> dict[str, str]:
    if tags is None:
        return {}
    return {key: str(values[0]) for key, values in tags.items() if values}


def _bitrate_kbps(bitrate: int | None) -> int | None:
    if not bitrate:
        return None
    return round(bitrate / 1000)


def _scalar(value: object) -> str:
    """One tag value as text; binary payloads (album art) become a size summary."""
    if isinstance(value, (bytes, bytearray)):
        return f"<{len(value)} bytes>"
    data = getattr(value, "data", None)  # ID3 APIC / MP4Cover carry bytes on .data
    if isinstance(data, (bytes, bytearray)):
        return f"<{len(data)} bytes>"
    return str(value)


def _render_value(value: object) -> str:
    """Flatten a frame or multi-value tag into one readable string."""
    text = getattr(value, "text", None)  # ID3 text frames keep their value(s) here
    if isinstance(text, str):
        return text
    if text is not None:
        return "; ".join(_scalar(v) for v in text)
    if isinstance(value, (list, tuple)):  # e.g. MP4 atoms hold a list of values
        return "; ".join(_scalar(v) for v in value)
    return _scalar(value)


def read_all_tags(path: Path) -> RawTagDump:
    """Read every stored tag (non-easy) and audio info from path without modifying it."""
    try:
        audio = mutagen.File(path)
    except (mutagen.MutagenError, OSError, ValueError) as exc:
        raise TagReadError(f"{type(exc).__name__}: {exc}") from exc
    if audio is None:
        raise TagReadError("unrecognised audio format")
    tags = audio.tags
    items = tuple((str(key), _render_value(value)) for key, value in tags.items()) if tags else ()
    info = audio.info
    return RawTagDump(
        items=items,
        duration_seconds=getattr(info, "length", None),
        bitrate_kbps=_bitrate_kbps(getattr(info, "bitrate", None)),
    )


def read_tags(path: Path) -> RawTags:
    """Read easy-style tags and audio info from path without modifying it."""
    try:
        audio = mutagen.File(path, easy=True)
    except (mutagen.MutagenError, OSError, ValueError) as exc:
        raise TagReadError(f"{type(exc).__name__}: {exc}") from exc
    if audio is None:
        raise TagReadError("unrecognised audio format")
    info = audio.info
    return RawTags(
        tags=_first_values(audio.tags),
        duration_seconds=getattr(info, "length", None),
        bitrate_kbps=_bitrate_kbps(getattr(info, "bitrate", None)),
    )

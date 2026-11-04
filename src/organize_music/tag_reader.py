"""Side-effect boundary: the only module that imports mutagen. Read-only."""

from pathlib import Path

import mutagen

from organize_music.models import RawTags


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

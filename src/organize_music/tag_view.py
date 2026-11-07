"""Pure rendering of one track's interpreted tags into text lines. No disk access."""

from organize_music.models import FIELD_NAMES, Source, TrackMetadata

_LABEL_WIDTH = max(len(name) for name in (*FIELD_NAMES, "duration", "bitrate"))


def _label(name: str) -> str:
    return f"  {name:<{_LABEL_WIDTH}} :"


def render_tags(track: TrackMetadata) -> str:
    """Render one track's path, fields (with provenance), and audio info as text.

    An unreadable file reports its error instead of a column of blank fields.
    """
    lines = [str(track.record.path)]
    if track.error is not None:
        lines.append(f"{_label('error')} {track.error}")
        return "\n".join(lines)
    for name in FIELD_NAMES:
        field = getattr(track, name)
        if field.source is Source.MISSING:
            lines.append(f"{_label(name)} — (missing)")
        else:
            lines.append(f"{_label(name)} {field.value}  ({field.source})")
    if track.duration_seconds is not None:
        lines.append(f"{_label('duration')} {track.duration_seconds:.0f} s")
    if track.bitrate_kbps is not None:
        lines.append(f"{_label('bitrate')} {track.bitrate_kbps} kbps")
    return "\n".join(lines)

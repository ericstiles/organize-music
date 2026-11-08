"""Pure fallback parsing of metadata from filenames and folder names.

Conservative by design: when a pattern is ambiguous, the field is left out
rather than guessed. Every value produced here is labelled FILENAME/FOLDER.
"""

import re
from pathlib import Path

Parsed = dict[str, str | int]

_COPY_SUFFIX = re.compile(r"\s*\(\d+\)$")
_DOUBLE_NUMBER = re.compile(r"^\d{1,3}\s*-\s*\d{1,3}\s*-\s*(?P<rest>.+)$")
_TRACK_PUNCT = re.compile(r"^(?P<num>\d{1,3})\s*[-._]\s*(?P<rest>.+)$")
_TRACK_SPACE = re.compile(r"^(?P<num>\d{1,3})\s+(?P<rest>.+)$")
_LEADING_PAREN = re.compile(r"^\((?P<genre>[^()]+)\)\s*-?\s*(?P<rest>.+)$")
# A separator needs whitespace on at least one side, so "Jay-Z" never splits.
_SEPARATOR = re.compile(r"\s+-\s*|\s*-\s+")
_YEAR_FIRST = re.compile(r"^(?P<year>(?:19|20)\d{2})\s*-\s*(?P<album>.+)$")
_YEAR_LAST = re.compile(r"^(?P<album>.+?)\s*[(\[](?P<year>(?:19|20)\d{2})[)\]]$")
_ARTIST_ALBUM_DEPTH = 2


def _split_track(text: str) -> tuple[int | None, str]:
    match = _TRACK_PUNCT.match(text)
    if match is None:
        match = _TRACK_SPACE.match(text)
        # "50 Cent - In Da Club": an unpadded number before an Artist - Title split
        # is more likely part of the artist than a track number.
        if match and not match["num"].startswith("0") and _SEPARATOR.search(match["rest"]):
            return None, text
    if match is None or int(match["num"]) == 0:
        return None, text
    return int(match["num"]), match["rest"]


def _split_genre(text: str) -> tuple[str | None, str]:
    match = _LEADING_PAREN.match(text)
    if match and _SEPARATOR.search(match["rest"]):
        return match["genre"].strip(), match["rest"]
    return None, text


def _split_artist_title(text: str) -> Parsed:
    parts = [part.strip() for part in _SEPARATOR.split(text) if part.strip()]
    if len(parts) >= 2:
        return {"artist": parts[0], "title": " - ".join(parts[1:])}
    return {"title": parts[0]} if parts else {}


def parse_filename(stem: str) -> Parsed:
    """Extract track_number, genre, artist and title from a filename stem."""
    text = _COPY_SUFFIX.sub("", stem).strip()
    if not text:
        return {}
    parsed: Parsed = {}
    double = _DOUBLE_NUMBER.match(text)
    if double:
        text = double["rest"]
    else:
        track, text = _split_track(text)
        if track is not None:
            parsed["track_number"] = track
    genre, text = _split_genre(text)
    if genre:
        parsed["genre"] = genre
    return {**parsed, **_split_artist_title(text)}


def _split_album_year(name: str) -> Parsed:
    for pattern in (_YEAR_FIRST, _YEAR_LAST):
        match = pattern.match(name)
        if match:
            return {"album": match["album"].strip(), "year": int(match["year"])}
    return {"album": name}


def parse_folders(relative_path: Path, skip_folders: frozenset[str] = frozenset()) -> Parsed:
    """Artist/album/year from an Artist/Album/file layout; nothing for any other depth.

    A top-level folder in skip_folders is a collection, not an artist, so its
    files get no artist/album guess from the folder names.
    """
    folders = relative_path.parts[:-1]
    if len(folders) != _ARTIST_ALBUM_DEPTH or folders[0] in skip_folders:
        return {}
    artist, album_dir = folders
    return {"artist": artist, **_split_album_year(album_dir)}

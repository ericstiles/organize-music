"""Table-driven tests for filename/folder fallback parsing.

Stems are real examples from docs/LIBRARY_SURVEY.md.
"""

from pathlib import Path

import pytest

from organize_music.filename_parse import parse_filename, parse_folders


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        ("01 Billie Jean", {"track_number": 1, "title": "Billie Jean"}),
        ("10 Angel Dust", {"track_number": 10, "title": "Angel Dust"}),
        ("01 15 Step", {"track_number": 1, "title": "15 Step"}),
        ("01-hotel intro", {"track_number": 1, "title": "hotel intro"}),
        ("03. Sweet Emotion", {"track_number": 3, "title": "Sweet Emotion"}),
        (
            "01 - Let Me Touch You For Awhile",
            {"track_number": 1, "title": "Let Me Touch You For Awhile"},
        ),
        (
            "01 - Ciara featuring Petey Pablo - Goodies",
            {"track_number": 1, "artist": "Ciara featuring Petey Pablo", "title": "Goodies"},
        ),
        (
            "(Old School Rap) De La Soul - Me Myself And I(1)",
            {"genre": "Old School Rap", "artist": "De La Soul", "title": "Me Myself And I"},
        ),
        (
            "(Techno) - Dj Sammy Vs Gigi D'agostino - Flying To Heaven",
            {
                "genre": "Techno",
                "artist": "Dj Sammy Vs Gigi D'agostino",
                "title": "Flying To Heaven",
            },
        ),
        (
            "(Mob Hits) -Louis Prima - When You'Re Smiling",
            {"genre": "Mob Hits", "artist": "Louis Prima", "title": "When You'Re Smiling"},
        ),
        (
            "Despina Vandi - Opa Opa - Video Edit",
            {"artist": "Despina Vandi", "title": "Opa Opa - Video Edit"},
        ),
        ("Fat Boys- Human Beat Box", {"artist": "Fat Boys", "title": "Human Beat Box"}),
    ],
)
def test_common_patterns(stem: str, expected: dict[str, object]) -> None:
    assert parse_filename(stem) == expected


@pytest.mark.parametrize(
    ("stem", "expected"),
    [
        # Leading number that is part of the artist, not a track number.
        ("50 Cent - In Da Club", {"artist": "50 Cent", "title": "In Da Club"}),
        # Two numbers: disc/track or track/total is ambiguous -> neither is guessed.
        ("01 - 12 - Ohm Sweet Ohm", {"title": "Ohm Sweet Ohm"}),
        # Leading parentheses without an Artist - Title split are not a genre.
        (
            "(M Project Ft Simple Minds) Dont You Forget About Me",
            {"title": "(M Project Ft Simple Minds) Dont You Forget About Me"},
        ),
        # Hyphen without spaces is part of a name, not a separator.
        ("Wilco-Either Way", {"title": "Wilco-Either Way"}),
        ("Jay-Z", {"title": "Jay-Z"}),
        # Track 0 is not a track.
        ("00 Hidden", {"title": "00 Hidden"}),
        ("oar2003-03-13d1t01", {"title": "oar2003-03-13d1t01"}),
        ("", {}),
        ("   ", {}),
        ("(2)", {}),
    ],
)
def test_ambiguous_input_is_not_guessed(stem: str, expected: dict[str, object]) -> None:
    assert parse_filename(stem) == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("Carbon Leaf/Echo Echo/01.mp3", {"artist": "Carbon Leaf", "album": "Echo Echo"}),
        ("Queen/1975 - Queen II/01.mp3", {"artist": "Queen", "album": "Queen II", "year": 1975}),
        ("Queen/Queen II (1974)/01.mp3", {"artist": "Queen", "album": "Queen II", "year": 1974}),
        ("Queen/Queen II [1974]/01.mp3", {"artist": "Queen", "album": "Queen II", "year": 1974}),
        ("Queen/1066 - Hastings/01.mp3", {"artist": "Queen", "album": "1066 - Hastings"}),
        # Only the Artist/Album/file shape is trusted.
        ("loose.mp3", {}),
        ("ipod_favs/song.mp3", {}),
        ("music/Moby/Hotel/Moby/01.mp3", {}),
    ],
)
def test_parse_folders(path: str, expected: dict[str, object]) -> None:
    assert parse_folders(Path(path)) == expected

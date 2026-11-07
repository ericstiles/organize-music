"""Shared fixtures: a tiny on-disk library built from silent audio files."""

import shutil
from pathlib import Path

import mutagen
import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def isolate_config(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Point config discovery at an empty dir so tests never read a real config.yaml."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path_factory.mktemp("xdg")))


def make_track(dest: Path, source: str, tags: dict[str, str]) -> Path:
    """Copy a silent fixture to dest and apply easy-style tags."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / source, dest)
    audio = mutagen.File(dest, easy=True)
    if audio.tags is None:
        audio.add_tags()
    for key, value in tags.items():
        audio[key] = value
    audio.save()
    return dest


@pytest.fixture
def library(tmp_path: Path) -> Path:
    """A mini library mirroring layouts seen in docs/LIBRARY_SURVEY.md."""
    root = tmp_path / "Music"
    make_track(
        root / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3",
        "silence.mp3",
        {
            "artist": "Carbon Leaf",
            "album": "Echo Echo",
            "title": "Learn To Fly",
            "tracknumber": "1/12",
            "date": "2001-05-01",
            "genre": "Rock",
        },
    )
    make_track(
        root / "Jay-Z" / "The Blueprint" / "02 Takeover.m4a",
        "silence.m4a",
        {"artist": "Jay-Z", "album": "The Blueprint", "title": "Takeover", "tracknumber": "2"},
    )
    make_track(root / "01 Billie Jean.MP3", "silence.mp3", {})
    (root / "cover.jpg").write_bytes(b"\xff\xd8not-really-a-jpeg")
    (root / "broken.mp3").write_bytes(b"")
    return root

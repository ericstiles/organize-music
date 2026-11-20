"""Tests for YAML configuration loading, validation, and overrides."""

from pathlib import Path

import pytest

from organize_music.config import DEFAULTS, Config, ConfigError, load_config


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_no_file_and_no_xdg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))

    monkeypatch.delenv("MUSIC_LIB", raising=False)
    monkeypatch.delenv("MUSIC_QUARANTINE", raising=False)

    config = load_config(None)

    assert config.library is None
    assert config.quarantine is None
    assert config.folder_format == DEFAULTS["folder_format"]
    assert "ipod_favs" in config.skip_folders


def test_file_values_win_over_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/pi")
    path = write(
        tmp_path,
        "library: /music\nindex: /state/i.db\nreports: /out\n"
        'quarantine: /q\nfolder_format: "${artist}/${title}.${ext}"\n'
        "skip_folders: [junk, copies]\n",
    )

    config = load_config(path)

    assert config == Config(
        library=Path("/music"),
        index=Path("/state/i.db"),
        reports=Path("/out"),
        quarantine=Path("/q"),
        folder_format="${artist}/${title}.${ext}",
        skip_folders=("junk", "copies"),
        library_mount=Path("/media/ets04uga/Extreme"),
        work_dir=Path("/media/ets04uga/Extreme/PlaceHereToKeepFromWork/_organize_music_work"),
        purge_dir=Path("/media/ets04uga/Extreme/PlaceHereToKeepFromWork/purge"),
        state_dir=Path("/home/pi/.local/share/organize_music"),
        bind_host="127.0.0.1",
        bind_port=8765,
        mutations_enabled=False,
    )


def test_partial_file_fills_rest_from_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, "library: /onlythis\n"))

    assert config.library == Path("/onlythis")
    assert config.folder_format == DEFAULTS["folder_format"]


def test_paths_are_user_expanded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/pi")

    config = load_config(write(tmp_path, "index: ~/state/index.db\n"))

    assert config.index == Path("/home/pi/state/index.db")


def test_overrides_win_over_file(tmp_path: Path) -> None:
    path = write(tmp_path, "library: /music\nindex: /a.db\n")

    config = load_config(path, overrides={"index": Path("/override.db")})

    assert config.index == Path("/override.db")
    assert config.library == Path("/music")


def test_none_overrides_are_ignored(tmp_path: Path) -> None:
    path = write(tmp_path, "library: /music\n")

    config = load_config(path, overrides={"library": None})

    assert config.library == Path("/music")


def test_explicit_missing_file_fails_fast(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_default_xdg_file_is_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_dir = tmp_path / "xdg" / "organize_music"
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "config.yaml").write_text("library: /from/xdg\n", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    assert load_config(None).library == Path("/from/xdg")


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="unknown.*nonsense"):
        load_config(write(tmp_path, "nonsense: 1\n"))


def test_non_mapping_file_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="mapping"):
        load_config(write(tmp_path, "- just\n- a list\n"))


def test_wrong_type_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="folder_format"):
        load_config(write(tmp_path, "folder_format: [not, a, string]\n"))


def test_skip_folders_must_be_list_of_strings(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="skip_folders"):
        load_config(write(tmp_path, "skip_folders: 5\n"))


def test_index_must_be_outside_library(tmp_path: Path) -> None:
    path = write(tmp_path, "library: /music\nindex: /music/state/i.db\n")

    with pytest.raises(ConfigError, match="index.*outside"):
        load_config(path)


def test_malformed_yaml_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="could not parse"):
        load_config(write(tmp_path, "key: [unclosed\n"))


def test_empty_file_yields_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, ""))

    assert config.folder_format == DEFAULTS["folder_format"]


def test_non_string_path_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="library must be a path string"):
        load_config(write(tmp_path, "library: 123\n"))


def test_library_and_quarantine_come_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    monkeypatch.setenv("MUSIC_LIB", str(tmp_path / "lib" / "Music"))
    monkeypatch.setenv("MUSIC_QUARANTINE", str(tmp_path / "lib" / "_q"))

    config = load_config(None)

    assert config.library == tmp_path / "lib" / "Music"
    assert config.quarantine == tmp_path / "lib" / "_q"


def test_quarantine_defaults_next_to_library_when_only_library_is_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    monkeypatch.setenv("MUSIC_LIB", str(tmp_path / "lib" / "Music"))
    monkeypatch.delenv("MUSIC_QUARANTINE", raising=False)

    config = load_config(None)

    assert config.quarantine == tmp_path / "lib" / "_quarantine"


def test_default_index_outside_deploy_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    monkeypatch.delenv("MUSIC_LIB", raising=False)
    monkeypatch.delenv("MUSIC_QUARANTINE", raising=False)

    config = load_config(None)

    # The default index must live under the XDG data dir, never under the
    # deploy target (~/$PI_DIR, e.g. ~/organize_music), so an rsync --delete
    # of the deploy dir cannot delete the index database.
    expected = tmp_path / ".local" / "share" / "organize_music" / "index.db"
    assert config.index == expected
    assert not config.index.is_relative_to(tmp_path / "organize_music")


def test_deploy_script_excludes_state_directory() -> None:
    deploy = Path(__file__).resolve().parent.parent / "scripts" / "deploy_to_pi.sh"
    assert deploy.is_file()

    # rsync --delete into the deploy dir must exclude state/ so the index
    # database (which lives there by default) survives every deploy.
    assert "--exclude 'state/'" in deploy.read_text(encoding="utf-8")


def test_new_web_keys_have_documented_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    monkeypatch.setenv("HOME", "/home/pi")
    monkeypatch.delenv("MUSIC_LIB", raising=False)
    monkeypatch.delenv("MUSIC_QUARANTINE", raising=False)

    config = load_config(None)

    assert config.library_mount == Path("/media/ets04uga/Extreme")
    assert config.work_dir == Path(
        "/media/ets04uga/Extreme/PlaceHereToKeepFromWork/_organize_music_work"
    )
    assert config.purge_dir == Path("/media/ets04uga/Extreme/PlaceHereToKeepFromWork/purge")
    assert config.state_dir == Path("/home/pi/.local/share/organize_music")
    assert config.bind_host == "127.0.0.1"
    assert config.bind_port == 8765
    assert config.mutations_enabled is False


def test_state_dir_default_expands_user(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HOME", "/home/pi")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))

    config = load_config(None)

    assert config.state_dir == Path("/home/pi/.local/share/organize_music")


def test_work_dir_inside_library_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, "library: /music\nwork_dir: /music/here\n")

    with pytest.raises(ConfigError, match="work_dir.*outside"):
        load_config(path)


def test_purge_dir_inside_library_is_rejected(tmp_path: Path) -> None:
    path = write(tmp_path, "library: /music\npurge_dir: /music/here\n")

    with pytest.raises(ConfigError, match="purge_dir.*outside"):
        load_config(path)


def test_bind_port_zero_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="bind_port"):
        load_config(write(tmp_path, "bind_port: 0\n"))


def test_bind_port_above_65535_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="bind_port"):
        load_config(write(tmp_path, "bind_port: 70000\n"))


def test_mutation_flag_must_be_a_bool(tmp_path: Path) -> None:
    # YAML `yes` parses to the bool True, so pin a non-bool string explicitly.
    with pytest.raises(ConfigError, match="mutations_enabled"):
        load_config(write(tmp_path, "mutations_enabled: 'yes'\n"))

"""YAML configuration: one file for all settings. Read-only; the tool never writes it.

Resolution order for each setting: CLI override > config file > built-in default.
The file is looked up at --config PATH, else $XDG_CONFIG_HOME/organize_music/config.yaml.
Unset library/quarantine fall back to $MUSIC_LIB / $MUSIC_QUARANTINE; quarantine otherwise
defaults to `_quarantine` beside the library. Validation fails fast with a clear message.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULTS: dict[str, object] = {
    "library": None,
    "index": "~/.local/share/organize_music/index.db",
    "reports": "~/organize_music/reports",
    "quarantine": None,
    "folder_format": "${artist}/${album}/${track}-${title}.${ext}",
    "skip_folders": ["Music2", "music", "OrganizesByGenre", "ipod_favs", "osx_sd_card_a_to_b"],
    # Web-server / mutation settings (Phase 1). No CLI equivalents yet.
    "library_mount": "/media/ets04uga/Extreme",
    "work_dir": "/media/ets04uga/Extreme/PlaceHereToKeepFromWork/_organize_music_work",
    "purge_dir": "/media/ets04uga/Extreme/PlaceHereToKeepFromWork/purge",
    "state_dir": "~/.local/share/organize_music",
    "bind_host": "127.0.0.1",
    "bind_port": 8765,
    "mutations_enabled": False,
}
_PATH_KEYS = ("library", "index", "reports", "quarantine")
# Everything below must live outside the library root, so rsync --delete and a
# stray scan can never touch it. work_dir/purge_dir join index/reports/quarantine.
_OUTSIDE_LIBRARY = ("index", "reports", "quarantine", "work_dir", "purge_dir")


class ConfigError(Exception):
    """The configuration file is missing (when named), malformed, or invalid."""


@dataclass(frozen=True)
class Config:
    library: Path | None
    index: Path
    reports: Path
    quarantine: Path | None
    folder_format: str
    skip_folders: tuple[str, ...]
    # Web-server / mutation settings (Phase 1).
    library_mount: Path
    work_dir: Path
    purge_dir: Path
    state_dir: Path
    bind_host: str
    bind_port: int
    mutations_enabled: bool


def _default_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(config_home) / "organize_music" / "config.yaml"


def _read_file(path: Path | None) -> dict[str, object]:
    if path is not None:
        if not path.is_file():
            raise ConfigError(f"config file not found: {path}")
        source = path
    else:
        source = _default_path()
        if not source.is_file():
            return {}
    try:
        loaded = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"could not parse {source}: {exc}") from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, Mapping):
        raise ConfigError(f"{source} must be a mapping of settings, got {type(loaded).__name__}")
    unknown = set(loaded) - set(DEFAULTS)
    if unknown:
        raise ConfigError(f"unknown config keys: {', '.join(sorted(map(str, unknown)))}")
    return dict(loaded)


def _as_path(key: str, value: object) -> Path:
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a path string, got {type(value).__name__}")
    return Path(value).expanduser()


def _as_str(key: str, value: object) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{key} must be a string, got {type(value).__name__}")
    return value


def _as_str_list(key: str, value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ConfigError(f"{key} must be a list of strings")
    return tuple(value)


def _coerce_bool(key: str, value: object) -> bool:
    # bool is a subclass of int, so test it first: 1/0 must not pass.
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean, got {type(value).__name__}")
    return value


def _coerce_int(key: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer, got {type(value).__name__}")
    return value


def _validate_layout(config: Config) -> None:
    if config.library is None:
        return
    library = config.library.resolve()
    for key in _OUTSIDE_LIBRARY:
        path: Path | None = getattr(config, key)
        if path is not None and path.resolve().is_relative_to(library):
            raise ConfigError(f"{key} must be outside the library: {path}")


def load_config(path: Path | None, overrides: Mapping[str, object] | None = None) -> Config:
    """Load and validate configuration, applying non-None overrides last."""
    values = {**DEFAULTS, **_read_file(path)}
    for key, value in (overrides or {}).items():
        if value is not None:
            values[key] = value

    library = _optional_path("library", values["library"], "MUSIC_LIB")
    quarantine = _optional_path("quarantine", values["quarantine"], "MUSIC_QUARANTINE")
    if quarantine is None and library is not None:
        quarantine = library.parent / "_quarantine"

    bind_port = _coerce_int("bind_port", values["bind_port"])
    if not 1 <= bind_port <= 65535:
        raise ConfigError(f"bind_port must be 1-65535, got {bind_port}")

    config = Config(
        library=library,
        index=_coerce("index", values["index"]),
        reports=_coerce("reports", values["reports"]),
        quarantine=quarantine,
        folder_format=_as_str("folder_format", values["folder_format"]),
        skip_folders=_as_str_list("skip_folders", values["skip_folders"]),
        library_mount=_coerce("library_mount", values["library_mount"]),
        work_dir=_coerce("work_dir", values["work_dir"]),
        purge_dir=_coerce("purge_dir", values["purge_dir"]),
        state_dir=_coerce("state_dir", values["state_dir"]),
        bind_host=_as_str("bind_host", values["bind_host"]),
        bind_port=bind_port,
        mutations_enabled=_coerce_bool("mutations_enabled", values["mutations_enabled"]),
    )
    _validate_layout(config)
    return config


def _coerce(key: str, value: object) -> Path:
    """Accept a Path (from an override) or a string (from file/defaults)."""
    return value if isinstance(value, Path) else _as_path(key, value)


def _optional_path(key: str, value: object, env_var: str) -> Path | None:
    """A path from the setting, else from the environment variable, else None."""
    if value is None:
        value = os.environ.get(env_var) or None
    return None if value is None else _coerce(key, value)

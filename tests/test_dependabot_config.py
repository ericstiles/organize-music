"""Tests for the Dependabot configuration (.github/dependabot.yml).

The config must keep the pinned dependencies (pyproject.toml,
requirements-dev.txt) and the pinned workflow actions (.github/workflows/)
updated automatically, with minor and patch updates grouped so each
ecosystem arrives as a single PR.
"""

from pathlib import Path

import yaml

CONFIG = Path(__file__).resolve().parent.parent / ".github" / "dependabot.yml"


def _load() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _entry(config: dict, ecosystem: str) -> dict:
    updates = config.get("updates")
    assert isinstance(updates, list), "config has no updates list"
    for entry in updates:
        if entry.get("package-ecosystem") == ecosystem:
            return entry
    raise AssertionError(f"no updates entry for {ecosystem!r}")


def test_dependabot_covers_pip_and_github_actions() -> None:
    config = _load()
    assert config.get("version") == 2, "must declare version 2"
    ecosystems = {
        entry.get("package-ecosystem")
        for entry in config.get("updates", [])
        if isinstance(entry, dict)
    }
    assert ecosystems == {"pip", "github-actions"}, (
        f"expected exactly pip and github-actions, got {ecosystems}"
    )
    for ecosystem in ("pip", "github-actions"):
        entry = _entry(config, ecosystem)
        assert entry.get("directory") == "/"
    pip_entry = _entry(config, "pip")
    assert pip_entry.get("open-pull-requests-limit") == 5
    assert _entry(config, "pip").get("commit-message", {}).get("prefix") == "chore(deps)"
    assert _entry(config, "github-actions").get("commit-message", {}).get("prefix") == "ci(deps)"


def test_dependabot_schedules_are_weekly() -> None:
    config = _load()
    for entry in config.get("updates", []):
        schedule = entry.get("schedule")
        assert isinstance(schedule, dict) and schedule.get("interval") == "weekly", (
            f"{entry.get('package-ecosystem')!r} must update weekly"
        )


def test_dependabot_groups_minor_and_patch() -> None:
    config = _load()
    for entry in config.get("updates", []):
        groups = entry.get("groups")
        assert isinstance(groups, list) and groups, (
            f"{entry.get('package-ecosystem')!r} must declare a groups list"
        )
        assert any(group.get("update-types") == ["minor", "patch"] for group in groups), (
            f"{entry.get('package-ecosystem')!r} must group minor and patch updates"
        )

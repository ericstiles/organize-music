"""Tests for the GitHub Actions CI workflow (.github/workflows/ci.yml).

PyYAML parses the bare YAML key ``on`` as the boolean ``True``, so the
triggers mapping is read as ``workflow[True]`` (and never via the string
"on").
"""

from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # PyYAML turns the bare key ``on`` into boolean True.
    triggers = workflow.get(True, workflow.get("on"))
    assert isinstance(triggers, dict), "workflow has no triggers mapping"
    return triggers


def _job(workflow: dict) -> dict:
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict) and len(jobs) == 1, "expected exactly one job"
    return next(iter(jobs.values()))


def _runs(workflow: dict) -> list[str]:
    """Run commands of every step that has a ``run`` key, in order."""
    return [step.get("run", "") for step in _job(workflow)["steps"] if "run" in step]


def test_ci_workflow_runs_on_pull_request_to_main() -> None:
    workflow = _load()
    triggers = _triggers(workflow)
    pull_request = triggers.get("pull_request")
    assert pull_request is not None, "missing pull_request trigger"
    assert pull_request.get("branches") == ["main"]
    assert pull_request.get("types") == ["opened", "synchronize", "reopened"]
    push = triggers.get("push")
    assert push is not None, "missing push trigger"
    assert push.get("branches") == ["main"]
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target" not in raw


def test_ci_workflow_runs_quality_gate_steps() -> None:
    workflow = _load()
    job = _job(workflow)
    actions = [step.get("uses", "") for step in job["steps"] if "uses" in step]
    assert any(action.startswith("actions/checkout@") for action in actions)
    runs = _runs(workflow)
    assert any("-e '.[dev]'" in run for run in runs), "no editable dev install"
    assert any("requirements-dev.txt" in run for run in runs)
    assert any("pip wheel" in run for run in runs), "no wheel build step"
    all_runs = "\n".join(runs)
    assert "ruff check ." in all_runs
    assert "ruff format --check ." in all_runs
    assert "pytest" in all_runs


def test_ci_workflow_uses_python_3_12() -> None:
    workflow = _load()
    job = _job(workflow)
    setups = [
        step for step in job["steps"] if step.get("uses", "").startswith("actions/setup-python@")
    ]
    assert setups, "no actions/setup-python step"
    for step in setups:
        assert step.get("with", {}).get("python-version") == "3.12"
        assert step.get("with", {}).get("cache") == "pip"
        assert "pyproject.toml" in step["with"].get("cache-dependency-path", "")
        assert "requirements-dev.txt" in step["with"].get("cache-dependency-path", "")


def test_ci_workflow_permissions_are_read_only() -> None:
    workflow = _load()
    permissions = workflow.get("permissions")
    assert permissions == {"contents": "read"}
    raw = WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in raw, "workflow must not reference secrets"


def test_ci_workflow_enforces_80_percent_coverage() -> None:
    workflow = _load()
    runs = _runs(workflow)
    pytest_runs = [run for run in runs if "pytest" in run]
    assert pytest_runs, "no pytest step"
    assert any("--cov-fail-under=80" in run for run in pytest_runs)

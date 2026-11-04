"""End-to-end tests for the `organize-music meta` command."""

from pathlib import Path

import pytest

from organize_music import cli, pipeline


def snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
        for p in root.rglob("*")
        if p.is_file()
    }


def meta(root: Path, tmp_path: Path, *extra: str) -> int:
    """Run `meta` with the index and report kept in tmp_path (never ~/.local)."""
    args = ["meta", str(root), "--report", str(tmp_path / "r.md")]
    args += ["--index", str(tmp_path / "index.db"), *extra]
    return cli.main(args)


def test_meta_writes_markdown_report(library: Path, tmp_path: Path) -> None:
    assert meta(library, tmp_path) == 0

    text = (tmp_path / "r.md").read_text()
    assert "| Files scanned | 5 |" in text
    assert "| Audio files read | 4 |" in text
    assert "| Read errors | 1 |" in text
    assert "`01 Billie Jean.MP3`" in text


def test_meta_never_changes_the_library(library: Path, tmp_path: Path) -> None:
    before = snapshot(library)

    meta(library, tmp_path)

    assert snapshot(library) == before


def test_meta_summary_line_on_stderr(
    library: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    meta(library, tmp_path)

    err = capsys.readouterr().err
    assert "4 audio files (read 4, cached 0, pruned 0, errors 1)" in err
    assert "r.md" in err


def test_second_run_is_served_from_index(
    library: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    meta(library, tmp_path)
    capsys.readouterr()

    meta(library, tmp_path)

    assert "(read 0, cached 4," in capsys.readouterr().err


def test_rescan_flag_ignores_index(
    library: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    meta(library, tmp_path)
    capsys.readouterr()

    meta(library, tmp_path, "--rescan")

    assert "(read 4, cached 0," in capsys.readouterr().err


def test_meta_missing_root_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert meta(tmp_path / "nope", tmp_path) == 2
    assert "does not exist" in capsys.readouterr().err
    assert not (tmp_path / "r.md").exists()


def test_meta_refuses_report_inside_library(library: Path, tmp_path: Path) -> None:
    code = cli.main(
        ["meta", str(library), "--report", str(library / "r.md"), "--index", str(tmp_path / "i.db")]
    )

    assert code == 2
    assert not (library / "r.md").exists()


def test_meta_refuses_index_inside_library(library: Path, tmp_path: Path) -> None:
    code = cli.main(
        ["meta", str(library), "--report", str(tmp_path / "r.md"), "--index", str(library / "i.db")]
    )

    assert code == 2
    assert not (library / "i.db").exists()


def test_ctrl_c_exits_130_and_keeps_progress(
    library: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupted(*_args: object, **_kwargs: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "collect_metadata", interrupted)

    assert meta(library, tmp_path) == 130
    assert "re-run to resume" in capsys.readouterr().err
    assert not (tmp_path / "r.md").exists()


def test_default_index_honours_xdg_data_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

    assert cli.default_index_path() == tmp_path / "xdg" / "organize_music" / "index.db"


def test_default_index_falls_back_to_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)

    expected = Path.home() / ".local" / "share" / "organize_music" / "index.db"
    assert cli.default_index_path() == expected


def test_pipeline_progress_is_forwarded_to_stderr(
    library: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "PROGRESS_EVERY", 2)

    meta(library, tmp_path)

    assert "2/4 (read 2, cached 0)" in capsys.readouterr().err

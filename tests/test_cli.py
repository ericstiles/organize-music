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


def test_meta_reads_root_index_and_report_from_config(library: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        f"library: {library}\nindex: {tmp_path / 'i.db'}\nreports: {tmp_path / 'out'}\n",
        encoding="utf-8",
    )

    assert cli.main(["meta", "--config", str(config)]) == 0

    assert (tmp_path / "out" / "METADATA_REPORT.md").read_text().startswith("# Metadata Report")
    assert (tmp_path / "i.db").exists()


def test_cli_flags_override_config(library: Path, tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(
        f"library: {tmp_path / 'wrong'}\nindex: {tmp_path / 'c.db'}\n", encoding="utf-8"
    )

    code = cli.main(
        [
            "meta",
            str(library),
            "--config",
            str(config),
            "--index",
            str(tmp_path / "flag.db"),
            "--report",
            str(tmp_path / "r.md"),
        ]
    )

    assert code == 0
    assert (tmp_path / "flag.db").exists()
    assert not (tmp_path / "c.db").exists()


def test_invalid_config_exits_nonzero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    config = tmp_path / "config.yaml"
    config.write_text("bogus_key: 1\n", encoding="utf-8")

    assert cli.main(["meta", "--config", str(config)]) == 2
    assert "unknown config keys" in capsys.readouterr().err


def test_pipeline_progress_is_forwarded_to_stderr(
    library: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pipeline, "PROGRESS_EVERY", 2)

    meta(library, tmp_path)

    assert "2/4 (read 2, cached 0)" in capsys.readouterr().err


def hash_cmd(root: Path, tmp_path: Path, *extra: str) -> int:
    return cli.main(["hash", str(root), "--index", str(tmp_path / "index.db"), *extra])


def test_hash_summary_and_read_only(
    library: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import shutil

    copy = library / "ipod_favs" / "copy.mp3"
    copy.parent.mkdir()
    shutil.copyfile(library / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3", copy)
    before = snapshot(library)

    assert hash_cmd(library, tmp_path) == 0

    err = capsys.readouterr().err
    assert "2 candidate files (hashed 2, cached 0, failed 0, pruned 0)" in err
    assert "1 groups of byte-identical files" in err
    assert snapshot(library) == before


def test_hash_lists_failures(
    library: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import shutil

    from organize_music import hash_pipeline

    copy = library / "copy.mp3"
    shutil.copyfile(library / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3", copy)

    def denied(_path: Path) -> str:
        raise hash_pipeline.HashError("PermissionError: denied")

    monkeypatch.setattr(hash_pipeline, "md5_file", denied)

    hash_cmd(library, tmp_path, "--rehash")

    err = capsys.readouterr().err
    assert "failed 2" in err
    assert "  could not hash copy.mp3: PermissionError: denied" in err


def test_hash_refuses_index_inside_library(library: Path) -> None:
    code = cli.main(["hash", str(library), "--index", str(library / "i.db")])

    assert code == 2
    assert not (library / "i.db").exists()


def test_dupes_writes_report_and_is_read_only(
    library: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import shutil

    copy = library / "ipod_favs" / "copy.mp3"
    copy.parent.mkdir()
    shutil.copyfile(library / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3", copy)
    before = snapshot(library)
    report = tmp_path / "DUPLICATES_REPORT.md"

    code = cli.main(
        ["dupes", str(library), "--index", str(tmp_path / "i.db"), "--report", str(report)]
    )

    assert code == 0
    text = report.read_text()
    assert "| Groups of byte-identical files | 1 |" in text
    assert "- `ipod_favs/copy.mp3`" in text
    assert "1 groups, 1 extra copies" in capsys.readouterr().err
    assert snapshot(library) == before


def test_dupes_refuses_report_inside_library(library: Path, tmp_path: Path) -> None:
    code = cli.main(
        [
            "dupes",
            str(library),
            "--index",
            str(tmp_path / "i.db"),
            "--report",
            str(library / "d.md"),
        ]
    )

    assert code == 2
    assert not (library / "d.md").exists()


def tags_cmd(path: Path) -> int:
    return cli.main(["tags", str(path)])


def test_tags_prints_one_files_values_to_stdout(
    library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    track = library / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3"

    assert tags_cmd(track) == 0

    out = capsys.readouterr().out
    assert "01 Learn To Fly.mp3" in out
    assert "Carbon Leaf" in out
    assert "Learn To Fly" in out
    assert "Rock" in out
    assert "(tag)" not in out  # embedded tags are shown without a provenance label


def test_tags_scans_a_directory(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert tags_cmd(library) == 0

    out = capsys.readouterr().out
    assert "Learn To Fly" in out  # from Carbon Leaf
    assert "Takeover" in out  # from Jay-Z


def test_tags_is_read_only(library: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = snapshot(library)

    tags_cmd(library)

    assert snapshot(library) == before


def test_tags_missing_path_exits_nonzero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tags_cmd(tmp_path / "nope.mp3") == 2
    assert "does not exist" in capsys.readouterr().err


def test_tags_unreadable_file_reports_error_not_crash(
    library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tags_cmd(library / "broken.mp3") == 0

    out = capsys.readouterr().out
    assert "broken.mp3" in out


def test_tags_raw_dumps_tags_the_curated_view_omits(
    library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    import mutagen

    track = library / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3"
    audio = mutagen.File(track, easy=True)
    audio["composer"] = "Barry Privett"  # not one of the 8 curated fields
    audio.save()

    assert cli.main(["tags", "--raw", str(track)]) == 0

    out = capsys.readouterr().out
    assert "Barry Privett" in out  # raw surfaces every stored tag, not just the curated 8
    assert "(tag)" not in out  # raw mode carries no provenance labels


def test_tags_raw_summarises_embedded_art_as_bytes(
    library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from mutagen.id3 import APIC, ID3

    track = library / "Carbon Leaf" / "Echo Echo" / "01 Learn To Fly.mp3"
    id3 = ID3(track)
    id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=b"\xff\xd8\xff" * 20))
    id3.save()

    assert cli.main(["tags", "--raw", str(track)]) == 0

    out = capsys.readouterr().out
    assert "APIC" in out  # the art frame is listed
    assert "bytes" in out  # ...but its binary payload is summarised, not dumped


def test_meta_applies_skip_folders_from_config(library: Path, tmp_path: Path) -> None:
    import shutil

    # An untagged file under a collection folder: its only possible artist is the
    # folder name "Music2", which skip_folders must suppress.
    skip_dir = library / "Music2" / "SomeBand"
    skip_dir.mkdir(parents=True)
    shutil.copyfile(library / "01 Billie Jean.MP3", skip_dir / "99 Untagged.mp3")
    config = tmp_path / "config.yaml"
    config.write_text(
        f"library: {library}\nindex: {tmp_path / 'i.db'}\nreports: {tmp_path / 'out'}\n"
        "skip_folders: [Music2]\n",
        encoding="utf-8",
    )

    assert cli.main(["meta", "--config", str(config)]) == 0

    # With Music2 skipped, the file has no artist and lands in the missing sample.
    text = (tmp_path / "out" / "METADATA_REPORT.md").read_text()
    assert "Music2/SomeBand/99 Untagged.mp3" in text


def test_tags_dir_without_audio_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    only_art = tmp_path / "art"
    only_art.mkdir()
    (only_art / "cover.jpg").write_bytes(b"\xff\xd8jpeg")

    assert cli.main(["tags", str(only_art)]) == 2
    assert "no audio files" in capsys.readouterr().err


def test_tags_raw_on_unreadable_file_reports_error(
    library: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["tags", str(library / "broken.mp3"), "--raw"]) == 0
    assert "broken.mp3" in capsys.readouterr().out


def test_rename_command_is_gone() -> None:
    # The `rename` subcommand was dropped (Phase 0, C4): it is no longer a
    # recognised subcommand, so argparse rejects it with an "invalid choice"
    # error and exits 2 rather than dispatching run_rename.
    with pytest.raises(SystemExit) as exc:
        cli.main(["rename"])
    assert exc.value.code == 2

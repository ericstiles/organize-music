# organize_music

Tools and scripts for organizing a music library — reading track metadata,
de-duplicating, and tidying folder structure.

Companion to the music copied onto the Pi 5's 1 TB SSD
(`$MUSIC_LIB`) by the
[talk-to-pi](../talk-to-pi) project.

## Usage

The tools run **on the Pi** (`ssh $PI_HOST`) against
the library in place; you develop and run the tests on the Mac. Deploy and run:

```bash
# on the Mac, from the repo root — rsync + install into a venv on the Pi
scripts/deploy_to_pi.sh

# then on the Pi
ssh $PI_HOST
tmux new -s music
cd ~/organize_music && source .venv/bin/activate
LIB=$MUSIC_LIB
organize-music dupes "$LIB" --report ~/organize_music/reports/DUPLICATES_REPORT.md
```

Full, copy-pasteable examples with real output — deploy, the `meta`/`hash`/`dupes`
commands, and local development on the Mac — live in
[docs/EXAMPLES.md](docs/EXAMPLES.md).

## Layout

```
scripts/   # shell/python scripts (all scripts live here)
```

## Conventions

- All shell scripts go in `scripts/`.
- Markdown filenames are `UPPERCASE_WITH_UNDERSCORES.md`.
- Conventional commits only.

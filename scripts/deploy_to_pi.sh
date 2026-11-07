#!/usr/bin/env bash
# Copy this repo to the Pi and install it into a venv there.
# Touches only $PI_DIR on the Pi; never the music library.
#
# PI_HOST and PI_DIR come from the environment. They are set in .envrc
# (loaded by direnv after `direnv allow`). Without direnv, export them first:
#
#   PI_HOST=ets04uga@192.168.1.222 PI_DIR=organize_music scripts/deploy_to_pi.sh
set -euo pipefail

PI_HOST="${PI_HOST:?PI_HOST is not set — run 'direnv allow' or export it (see .envrc)}"
PI_DIR="${PI_DIR:-organize_music}"   # relative to the Pi user's home
MUSIC_LIB="${MUSIC_LIB:-/media/ets04uga/Extreme/PlaceHereToKeepFromWork/Music}"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Checking SSH to ${PI_HOST}"
ssh -o ConnectTimeout=8 -o BatchMode=yes "${PI_HOST}" true

echo "==> Syncing ${REPO_ROOT} -> ${PI_HOST}:~/${PI_DIR}"
rsync -a --delete \
  --exclude '.git/' --exclude '.venv/' --exclude '.beads/' --exclude 'reports/' \
  --exclude '__pycache__/' --exclude '.pytest_cache/' --exclude '.ruff_cache/' \
  --exclude '*.egg-info/' --exclude '.coverage' \
  "${REPO_ROOT}/" "${PI_HOST}:${PI_DIR}/"

echo "==> Installing into ~/${PI_DIR}/.venv on the Pi"
ssh "${PI_HOST}" bash -s -- "${PI_DIR}" "${MUSIC_LIB}" <<'REMOTE'
set -euo pipefail
PI_DIR="$1"
MUSIC_LIB="$2"
cd "$HOME/$PI_DIR"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv || { echo "python3-venv missing: sudo apt install python3-venv" >&2; exit 1; }
fi
.venv/bin/pip install -q --upgrade pip
# Editable install: rsync'd source is always live, and deps (mutagen, pyyaml) are
# resolved. A plain `pip install .` is a no-op when the version is unchanged, which
# silently ships stale code and skips new dependencies.
.venv/bin/pip install -q -e .
.venv/bin/organize-music --help >/dev/null
echo "installed: $(.venv/bin/python -c 'import mutagen; print("mutagen", mutagen.version_string)')"

# Install convenience aliases into ~/.bashrc (idempotent, replaces any prior block)
BASHRC="$HOME/.bashrc"
MARKER="# >>> organize_music aliases >>>"
if grep -qF "$MARKER" "$BASHRC" 2>/dev/null; then
  sed -i '/# >>> organize_music aliases >>>/,/# <<< organize_music aliases <<</d' "$BASHRC"
fi
{
  echo "$MARKER"
  echo "export MUSIC_LIB=\"$MUSIC_LIB\""
  echo "alias om='\$HOME/$PI_DIR/.venv/bin/organize-music'"
  echo "alias om-meta='om meta \"\$MUSIC_LIB\" --report \$HOME/$PI_DIR/reports/METADATA_REPORT.md'"
  echo "alias om-dupes='om dupes \"\$MUSIC_LIB\" --report \$HOME/$PI_DIR/reports/DUPLICATES_REPORT.md'"
  echo "# <<< organize_music aliases <<<"
} >> "$BASHRC"
echo "aliases installed in $BASHRC (reload: source ~/.bashrc)"
REMOTE

echo "==> Done. Run on the Pi, e.g.:"
echo "    ssh ${PI_HOST}"
echo "    source ~/.bashrc      # load aliases (first time only)"
echo "    tmux new -s music"
echo "    om --help             # alias for ~/${PI_DIR}/.venv/bin/organize-music"
echo "    om-meta               # meta scan of \$MUSIC_LIB -> reports/METADATA_REPORT.md"
echo "    om-dupes              # duplicates report"

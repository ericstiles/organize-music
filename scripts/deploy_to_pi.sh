#!/usr/bin/env bash
# Copy this repo to the Pi and install it into a venv there.
# Touches only $PI_DIR on the Pi; never the music library.
#
# Usage: scripts/deploy_to_pi.sh            (defaults below)
#        PI_HOST=user@pi-host PI_DIR=organize_music scripts/deploy_to_pi.sh
set -euo pipefail

PI_HOST="${PI_HOST:-user@pi-host}"
PI_DIR="${PI_DIR:-organize_music}"   # relative to the Pi user's home
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
ssh "${PI_HOST}" bash -s -- "${PI_DIR}" <<'REMOTE'
set -euo pipefail
cd "$HOME/$1"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv || { echo "python3-venv missing: sudo apt install python3-venv" >&2; exit 1; }
fi
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q .
.venv/bin/organize-music --help >/dev/null
echo "installed: $(.venv/bin/python -c 'import mutagen; print("mutagen", mutagen.version_string)')"
REMOTE

echo "==> Done. Run on the Pi, e.g.:"
echo "    ssh ${PI_HOST}"
echo "    tmux new -s music"
echo "    ~/${PI_DIR}/.venv/bin/organize-music meta /path/to/library-parent/Music \\"
echo "        --report ~/${PI_DIR}/reports/METADATA_REPORT.md"

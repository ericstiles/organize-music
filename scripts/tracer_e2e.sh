#!/usr/bin/env bash
# tracer_e2e.sh -- the tracer end to end (PLAN §12, issue organize_music-b8p.34).
#
# Proves the whole slice with a real process kill, not only simulated crashes:
#
#   1. build a temp library from tests/fixtures (20 copies, varied names),
#      write a temp config (mutations_enabled: true) and scan the library
#      into a fresh library.db with the small helper embedded below,
#   2. run `organize-music serve` in the background and rename one file over
#      HTTP (curl) -- the happy path,
#   3. restart serve with OM_FAULT_SLEEP_AFTER=applied in its environment,
#      start a second rename over HTTP, and kill -9 the server inside the
#      hook's 30 s sleep (the file is already renamed on disk, the row is
#      not yet committed); restart serve, assert the op settled per PLAN
#      §6.2, run `organize-music recover` (a no-op) and assert disk and DB
#      agree for every file.
#
# Prints 'TRACER OK' and exits 0 on success; exits non-zero on any mismatch.
# Not run by pytest. No Pi: everything is a temp library on this machine.
#
# Why the scan runs before the first serve: Phase 1 has no scan route on the
# server and no scan CLI command, and serve holds the writer lock for its
# lifetime, so an external scan cannot write to library.db while a server is
# running. The helper populates library.db first; the server then starts
# against the already-scanned library.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${REPO_DIR}/.venv/bin/python"
OM="${REPO_DIR}/.venv/bin/organize-music"
PORT="${OM_E2E_PORT:-47321}"
BASE_URL="http://127.0.0.1:${PORT}"

if [ ! -x "$PYTHON" ] || [ ! -x "$OM" ]; then
  echo "tracer_e2e: missing $PYTHON / $OM -- install first: python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'" >&2
  exit 1
fi
command -v curl >/dev/null 2>&1 || {
  echo "tracer_e2e: curl is required" >&2
  exit 1
}

unset OM_FAULT_SLEEP_AFTER
WORK="$(mktemp -d)"
LIBRARY="$WORK/library"
STATE="$WORK/state"
OM_WORK="$WORK/work"
PURGE="$WORK/purge"
CONFIG="$WORK/config.yaml"
HELPER="$WORK/scan_helper.py"
DB="$STATE/library.db"
FIXTURES="$REPO_DIR/tests/fixtures"
SERVER_PID=""
CURL_PID=""

fail() {
  echo "TRACER FAILED: $*" >&2
  exit 1
}

cleanup() {
  trap - EXIT INT TERM
  if [ -n "$SERVER_PID" ]; then
    kill "$SERVER_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5 6 7 8 9 10; do
      kill -0 "$SERVER_PID" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$SERVER_PID" 2>/dev/null || true
  fi
  [ -n "$CURL_PID" ] && kill "$CURL_PID" 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# ---------------------------------------------------------------------------
# the small helper: scan, and read-only queries over library.db / drafts.db
# ---------------------------------------------------------------------------
cat > "$HELPER" <<'PYEOF'
"""Tracer E2E helper (issue b8p.34): scan, plus read-only state queries.

Usage: scan_helper.py <command> <library> <state> [extra...]

Commands:
  scan              walk <library> into <state>/library.db (fresh rows)
  digests           one content SHA-256 per library file, one per line
  file-id PATH      the file_id of the row at PATH (or 'none')
  row-of FILE_ID    'path row_version' of that row
  draft-id          latest draft batch_id in drafts.db (or 'none')
  op-state PATH     'state error_code' of the latest op for that expect_path
  batch-state PATH  'state succeeded failed' of that op's batch
  crash-check ID S D  per PLAN §6.2: consistent iff the op's terminal state
                    matches the row (by file_id) and the disk picture
  check             disk and DB agree: every present row on disk at its
                    path/size/mtime, every disk file has a row, and no
                    operation is left in flight
"""
import hashlib
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

AUDIO_EXTS = frozenset({"mp3", "m4a", "m4p", "ogg", "wma", "wav", "flac"})


def _open(db: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn


def main() -> int:
    from organize_music.db import migrate, open_writer
    from organize_music.db.files_repo import FilesRepo
    from organize_music.scanner import walk_library

    command = sys.argv[1]
    library = Path(sys.argv[2])
    state = Path(sys.argv[3])
    db = state / "library.db"
    extra = sys.argv[4:]

    if command == "scan":
        now = datetime.now(UTC).isoformat(timespec="seconds")
        conn = open_writer(db)
        try:
            migrate(conn, db, state / "backups", now)
            repo = FilesRepo(conn)
            count = 0
            for rec in walk_library(library):
                kind = "audio" if rec.ext in AUDIO_EXTS else "art"
                repo.insert_scanned(rec, kind, now)
                count += 1
            conn.commit()
        finally:
            conn.close()
        print(f"scan: {count} files into {db}")
        return 0

    if command == "digests":
        for path in sorted(p for p in library.rglob("*") if p.is_file()):
            print(hashlib.sha256(path.read_bytes()).hexdigest())
        return 0

    if command == "file-id":
        conn = _open(db)
        try:
            row = conn.execute(
                "SELECT file_id FROM files WHERE path = ?", (extra[0],)
            ).fetchone()
        finally:
            conn.close()
        print(row["file_id"] if row else "none")
        return 0

    if command == "row-of":
        conn = _open(db)
        try:
            row = conn.execute(
                "SELECT path, row_version FROM files WHERE file_id = ?", (extra[0],)
            ).fetchone()
        finally:
            conn.close()
        print(f"{row['path']} {row['row_version']}" if row else "none")
        return 0

    if command == "draft-id":
        conn = _open(state / "drafts.db")
        try:
            row = conn.execute(
                "SELECT batch_id FROM batches ORDER BY batch_id DESC LIMIT 1"
            ).fetchone()
        finally:
            conn.close()
        print(row["batch_id"] if row else "none")
        return 0

    if command == "op-state":
        conn = _open(db)
        try:
            row = conn.execute(
                "SELECT state, error_code FROM operations WHERE expect_path = ? "
                "ORDER BY op_id DESC LIMIT 1",
                (extra[0],),
            ).fetchone()
        finally:
            conn.close()
        print(f"{row['state']} {row['error_code'] or ''}".rstrip() if row else "none")
        return 0

    if command == "batch-state":
        conn = _open(db)
        try:
            row = conn.execute(
                "SELECT b.state, b.succeeded, b.failed FROM batches b "
                "JOIN operations o ON o.batch_id = b.batch_id "
                "WHERE o.expect_path = ? ORDER BY o.op_id DESC LIMIT 1",
                (extra[0],),
            ).fetchone()
        finally:
            conn.close()
        print(f"{row['state']} {row['succeeded']} {row['failed']}" if row else "none")
        return 0

    if command == "crash-check":
        file_id, src_rel, dst_rel = extra[0], extra[1], extra[2]
        conn = _open(db)
        try:
            op = conn.execute(
                "SELECT state, error_code FROM operations WHERE expect_path = ? "
                "ORDER BY op_id DESC LIMIT 1",
                (src_rel,),
            ).fetchone()
            row = conn.execute(
                "SELECT path, status FROM files WHERE file_id = ?", (file_id,)
            ).fetchone()
        finally:
            conn.close()
        if op is None or row is None:
            print(f"crash-check: MISMATCH: no op/row for {src_rel}")
            return 1
        state_name, err = op["state"], op["error_code"]
        disk_src = (library / src_rel).is_file()
        disk_dst = (library / dst_rel).is_file()
        if state_name == "committed":
            ok = row["path"] == dst_rel and disk_dst and not disk_src
        elif state_name == "failed":
            ok = row["path"] == src_rel and disk_src and not disk_dst
        else:
            ok = False  # needs_attention (or an in-flight state): a mismatch here
        print(
            f"crash-check: op={state_name} error={err} row={row['path']} "
            f"disk src={disk_src} dst={disk_dst}"
        )
        return 0 if ok else 1

    if command == "check":
        conn = _open(db)
        try:
            rows = conn.execute(
                "SELECT file_id, path, size, mtime_ns FROM files WHERE status = 'present'"
            ).fetchall()
            active = conn.execute(
                "SELECT op_id, state FROM operations "
                "WHERE state IN ('intent','staged','parked','applied')"
            ).fetchall()
        finally:
            conn.close()
        problems: list[str] = []
        for row in rows:
            target = library / row["path"]
            if not target.is_file():
                problems.append(f"row {row['file_id']} {row['path']}: missing on disk")
                continue
            st = target.stat()
            if st.st_size != row["size"]:
                problems.append(f"row {row['file_id']} {row['path']}: size differs")
            if st.st_mtime_ns != row["mtime_ns"]:
                problems.append(f"row {row['file_id']} {row['path']}: mtime differs")
        on_disk = {str(p.relative_to(library)) for p in library.rglob("*") if p.is_file()}
        in_db = {row["path"] for row in rows}
        for name in sorted(on_disk - in_db):
            problems.append(f"disk file {name}: no row")
        for name in sorted(in_db - on_disk):
            problems.append(f"row {name}: not on disk")
        for op in active:
            problems.append(f"op {op['op_id']} left in flight: {op['state']}")
        if problems:
            print("MISMATCH:")
            for problem in problems:
                print(f"  {problem}")
            return 1
        print(f"check: disk and DB agree ({len(rows)} present rows)")
        return 0

    print(f"unknown command: {command}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
PYEOF

# ---------------------------------------------------------------------------
# 1. temp library (20 copies of the two silent fixtures, varied names)
# ---------------------------------------------------------------------------
mkdir -p "$LIBRARY" "$STATE" "$OM_WORK" "$PURGE"
for i in 1 2 3 4 5 6 7 8 9 10; do
  n="$(printf '%03d' "$i")"
  cp -f "$FIXTURES/silence.mp3" "$LIBRARY/T${n}.mp3"
  cp -f "$FIXTURES/silence.m4a" "$LIBRARY/M${n}.m4a"
done
echo "tracer: temp library with 20 files under $LIBRARY" >&2

cat > "$CONFIG" <<EOF
library: $LIBRARY
index: $WORK/index.db
reports: $WORK/reports
work_dir: $OM_WORK
purge_dir: $PURGE
state_dir: $STATE
library_mount: /
bind_host: 127.0.0.1
bind_port: $PORT
mutations_enabled: true
EOF

# The scan runs before the first serve (see the header note).
"$PYTHON" "$HELPER" scan "$LIBRARY" "$STATE" >&2
DIGESTS_BEFORE="$("$PYTHON" "$HELPER" digests "$LIBRARY" "$STATE" | sort)"

# ---------------------------------------------------------------------------
# server lifecycle
# ---------------------------------------------------------------------------
start_server() {
  if [ "$1" = "applied" ]; then
    OM_FAULT_SLEEP_AFTER=applied "$OM" serve --config "$CONFIG" >"$WORK/serve.out" 2>"$WORK/serve.err" &
  else
    (
      unset OM_FAULT_SLEEP_AFTER
      exec "$OM" serve --config "$CONFIG" >"$WORK/serve.out" 2>"$WORK/serve.err"
    ) &
  fi
  SERVER_PID=$!
}

wait_server() {
  for i in $(seq 1 80); do
    if curl -sf "$BASE_URL/healthz" 2>/dev/null | grep -q '"ok":true'; then
      return 0
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      sed -n '1,30p' "$WORK/serve.err" >&2
      fail "server died during startup (log above)"
    fi
    sleep 0.5
  done
  sed -n '1,30p' "$WORK/serve.err" >&2
  fail "server not healthy within 40 s (log above)"
}

stop_server() {
  [ -n "$SERVER_PID" ] || return 0
  kill "$SERVER_PID" 2>/dev/null || true
  for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16; do
    kill -0 "$SERVER_PID" 2>/dev/null || break
    sleep 0.25
  done
  kill -9 "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  SERVER_PID=""
}

# Preview, confirm, and report one rename over HTTP. $1 = source rel path,
# $2 = new filename. Prints '<file_id> <preview_code> <confirm_code>'.
rename_over_http() {
  local file_id code draft code2
  file_id="$("$PYTHON" "$HELPER" file-id "$LIBRARY" "$STATE" "$1")"
  [ "$file_id" != "none" ] || fail "no row for $1 (scan did not see it?)"
  code="$(curl -s -o /dev/null -w '%{http_code}' -X POST \
    --data-urlencode "new_name=$2" "$BASE_URL/files/$file_id/rename")"
  [ "$code" = "200" ] || fail "preview of $1 -> $2 got HTTP $code"
  draft="$("$PYTHON" "$HELPER" draft-id "$LIBRARY" "$STATE")"
  [ "$draft" != "none" ] || fail "no draft batch stored for $1"
  code2="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$BASE_URL/batches/$draft/confirm")"
  [ "$code2" = "200" ] || fail "confirm of $1 -> $2 got HTTP $code2"
  echo "$file_id $code $code2"
}

# ---------------------------------------------------------------------------
# 2. happy path: serve, rename one file over HTTP, confirm success
# ---------------------------------------------------------------------------
echo "tracer: serve (no fault hook) on $BASE_URL" >&2
start_server ""
wait_server
RESULT_1="$(rename_over_http "T001.mp3" "T001-renamed.mp3")"
FILE_ID_1="$(printf '%s\n' "$RESULT_1" | cut -d' ' -f1)"
[ -f "$LIBRARY/T001-renamed.mp3" ] || fail "T001-renamed.mp3 missing on disk"
[ ! -e "$LIBRARY/T001.mp3" ] || fail "T001.mp3 still on disk"
[ "$("$PYTHON" "$HELPER" row-of "$LIBRARY" "$STATE" "$FILE_ID_1")" = "T001-renamed.mp3 2" ] \
  || fail "row for T001 not updated to T001-renamed.mp3 v2"
[ "$("$PYTHON" "$HELPER" op-state "$LIBRARY" "$STATE" T001.mp3)" = "committed" ] \
  || fail "T001 op did not commit"
[ "$("$PYTHON" "$HELPER" batch-state "$LIBRARY" "$STATE" T001.mp3)" = "completed 1 0" ] \
  || fail "T001 batch did not complete with one success"
echo "tracer: happy path: rename over HTTP committed" >&2
stop_server

# ---------------------------------------------------------------------------
# 3. crash phase: OM_FAULT_SLEEP_AFTER=applied, kill -9 inside the sleep
# ---------------------------------------------------------------------------
echo "tracer: serve with OM_FAULT_SLEEP_AFTER=applied on $BASE_URL" >&2
start_server applied
wait_server
FILE_ID_2="$("$PYTHON" "$HELPER" file-id "$LIBRARY" "$STATE" T002.mp3)"
[ "$FILE_ID_2" != "none" ] || fail "no row for T002.mp3"
CODE_P2="$(curl -s -o /dev/null -w '%{http_code}' -X POST \
  --data-urlencode "new_name=T002-crashed.mp3" "$BASE_URL/files/$FILE_ID_2/rename")"
[ "$CODE_P2" = "200" ] || fail "preview of T002.mp3 got HTTP $CODE_P2"
DRAFT_2="$("$PYTHON" "$HELPER" draft-id "$LIBRARY" "$STATE")"
[ "$DRAFT_2" != "none" ] || fail "no draft stored for T002.mp3"
# The confirm blocks in the hook's 30 s sleep, so it runs in the background;
# its outcome is judged from the database, not the HTTP code.
curl -s -o /dev/null -X POST "$BASE_URL/batches/$DRAFT_2/confirm" 2>/dev/null &
CURL_PID=$!
# Wait for the op to reach 'applied': the rename is done on disk and the hook
# is now inside its 30 s sleep. Break out early if it commits instead (the
# fault window was missed).
STATE_SEEN=""
for _ in $(seq 1 100); do
  STATE_SEEN="$("$PYTHON" "$HELPER" op-state "$LIBRARY" "$STATE" T002.mp3)"
  case "$STATE_SEEN" in
    applied* | committed*) break ;;
  esac
  sleep 0.2
done
case "$STATE_SEEN" in
  applied*)
    echo "tracer: kill -9 in the 30 s sleep after the op reached applied" >&2
    ;;
  committed*)
    fail "the op committed before the kill could land (fault hook not engaged, or the 30 s window was missed); re-run"
    ;;
  *)
    fail "the op never reached the fault window (last seen: ${STATE_SEEN:-none})"
    ;;
esac
kill -9 "$SERVER_PID" 2>/dev/null || true
wait "$SERVER_PID" 2>/dev/null || true
SERVER_PID=""
kill "$CURL_PID" 2>/dev/null || true
wait "$CURL_PID" 2>/dev/null || true
CURL_PID=""
AFTER_KILL="$("$PYTHON" "$HELPER" op-state "$LIBRARY" "$STATE" T002.mp3)"
case "$AFTER_KILL" in
  committed*)
    fail "kill -9 landed after the commit; the crash did not interrupt the op (re-run)"
    ;;
  *)
    echo "tracer: crash captured: op left in '${AFTER_KILL%% *}' after kill -9" >&2
    ;;
esac

# Restart: serve's startup recovery (PLAN §6.4) settles the crashed op before
# any job is accepted.
echo "tracer: restarted serve; its startup recovery now runs" >&2
start_server ""
wait_server
"$PYTHON" "$HELPER" crash-check "$LIBRARY" "$STATE" "$FILE_ID_2" T002.mp3 T002-crashed.mp3 >&2 \
  || fail "the crashed op did not settle to a consistent PLAN §6.2 outcome"
stop_server

# ---------------------------------------------------------------------------
# 4. recover is a no-op, and disk and DB agree for every file
# ---------------------------------------------------------------------------
set +e
RECOVER_OUT="$("$OM" recover --config "$CONFIG" 2>&1)"
RECOVER_RC=$?
set -e
printf '%s\n' "$RECOVER_OUT" >&2
[ "$RECOVER_RC" = "0" ] || fail "organize-music recover exited $RECOVER_RC"
printf '%s\n' "$RECOVER_OUT" | grep -q "recover: committed 0, failed 0; needs attention: none" \
  || fail "recover was not a no-op"
echo "tracer: recover was a no-op" >&2

"$PYTHON" "$HELPER" check "$LIBRARY" "$STATE" >&2 || fail "disk and DB disagree"
DIGESTS_AFTER="$("$PYTHON" "$HELPER" digests "$LIBRARY" "$STATE" | sort)"
[ "$DIGESTS_BEFORE" = "$DIGESTS_AFTER" ] || fail "the content multiset changed"

echo "TRACER OK"

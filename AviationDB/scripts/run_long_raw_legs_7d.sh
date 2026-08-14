#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-long-legs-7d"
LOG="$JOB_DIR/pipeline.log"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"
LABEL="travel-globe-long-raw-legs-7d"

mkdir -p "$JOB_DIR"

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$JOB_DIR/status.json" ]]; then
    /bin/cat "$JOB_DIR/status.json"
  else
    printf '%s\n' '{"state":"not_started"}'
  fi
  exit 0
fi

if [[ "${1:-}" == "stop" ]]; then
  if [[ -f "$PID_FILE" ]]; then
    pid="$(<"$PID_FILE")"
    if [[ -n "$pid" ]] && /bin/kill -0 "$pid" 2>/dev/null; then
      /bin/kill "$pid" 2>/dev/null || true
    fi
  fi
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  if ! /bin/mkdir "$LOCK_DIR" 2>/dev/null; then
    printf 'worker already running: %s\n' "$LOCK_DIR" >&2
    exit 0
  fi
  printf '%s\n' "$$" > "$PID_FILE"
  trap '/bin/rm -f "$PID_FILE"; /bin/rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  exec /usr/local/bin/python3 AviationDB/scripts/run_long_raw_legs_7d.py \
    --job-dir "$JOB_DIR" \
    --raw-root "$ROOT/AviationDB/data/raw/adsblol" \
    --airport-index "$ROOT/shared/offline-packs/core-global/airports-index.json"
fi

# The prior PTY worker is confirmed absent.  Replacing only this named launchd
# job is safe and lets the resumable manifest/checkpoints continue after an
# interrupted terminal session.
/bin/launchctl remove "$LABEL" 2>/dev/null || true
/bin/launchctl submit -l "$LABEL" -- /bin/bash "$ROOT/AviationDB/scripts/run_long_raw_legs_7d.sh" __worker
printf 'started background pipeline label=%s job_dir=%s log=%s status=%s\n' \
  "$LABEL" "$JOB_DIR" "$LOG" "$JOB_DIR/status.json"

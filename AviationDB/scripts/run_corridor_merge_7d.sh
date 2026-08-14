#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-corridor-7d"
LOG="$JOB_DIR/merge.log"
LOCK_DIR="$JOB_DIR/merge.lock"
PID_FILE="$JOB_DIR/merge.pid"

mkdir -p "$JOB_DIR"

if [[ "${1:-}" == "status" ]]; then
  cat "$JOB_DIR/merge-status.json" 2>/dev/null || echo '{"state":"not_started"}'
  exit 0
fi

if [[ "${1:-}" == "stop" ]]; then
  if [[ -f "$PID_FILE" ]]; then
    pid="$(<"$PID_FILE")"
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then kill "$pid" 2>/dev/null || true; fi
  fi
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then exit 0; fi
  echo $$ > "$PID_FILE"
  trap 'rm -f "$PID_FILE"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  exec /usr/local/bin/python3 AviationDB/scripts/merge_corridor_7d.py --job-dir "$JOB_DIR"
fi

launchctl remove travel-globe-corridor-merge-7d 2>/dev/null || true
launchctl submit -l travel-globe-corridor-merge-7d -- /bin/bash "$ROOT/AviationDB/scripts/run_corridor_merge_7d.sh" __worker
echo "started merge background pipeline job_dir=$JOB_DIR"

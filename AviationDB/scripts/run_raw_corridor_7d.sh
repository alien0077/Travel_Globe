#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-corridor-7d"
LOG="$JOB_DIR/pipeline.log"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"
STATUS="$JOB_DIR/status.json"

mkdir -p "$JOB_DIR"

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$STATUS" ]]; then cat "$STATUS"; else echo '{"state":"not_started"}'; fi
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
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "worker already running: $LOCK_DIR" >&2
    exit 0
  fi
  echo $$ > "$PID_FILE"
  trap 'rm -f "$PID_FILE"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  exec /usr/local/bin/python3 AviationDB/scripts/run_raw_corridor_7d.py --job-dir "$JOB_DIR"
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
  echo "already running pid=$(<"$PID_FILE")"
  exit 0
fi

nohup /bin/bash "$ROOT/AviationDB/scripts/run_raw_corridor_7d.sh" __worker >/dev/null 2>&1 &
pid=$!
echo "$pid" > "$PID_FILE"
echo "started pid=$pid job_dir=$JOB_DIR log=$LOG status=$STATUS"

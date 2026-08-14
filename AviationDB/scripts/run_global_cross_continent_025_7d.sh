#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-global-cross-continent-025-7d"
RAW_ROOT="$ROOT/AviationDB/data/raw/adsblol"
OUTPUT_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-cross-continent-7d-025"
LOG="$JOB_DIR/pipeline.log"
STATUS="$JOB_DIR/status.json"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"

mkdir -p "$JOB_DIR" "$OUTPUT_ROOT"

if [[ "${1:-}" == "status" ]]; then
  cat "$STATUS" 2>/dev/null || echo '{"state":"not_started"}'
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
  /usr/local/bin/python3 -m py_compile AviationDB/scripts/extract_global_cross_continent_corridors_7d.py
  exec /usr/local/bin/python3 AviationDB/scripts/extract_global_cross_continent_corridors_7d.py \
    --raw-root "$RAW_ROOT" \
    --output-root "$OUTPUT_ROOT" \
    --status "$STATUS" \
    --cell-deg 0.25 \
    --include-asia-northamerica
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
  echo "already running pid=$(<"$PID_FILE")"
  exit 0
fi
echo "Use a detached PTY/background runner to start this resumable worker: $ROOT/AviationDB/scripts/run_global_cross_continent_025_7d.sh __worker"

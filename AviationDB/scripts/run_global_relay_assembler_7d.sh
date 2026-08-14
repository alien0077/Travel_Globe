#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-relay-7d"
INPUT_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/corridor-7d-v2/global"
OUTPUT_ROOT="$INPUT_ROOT/relay-network"
LOG="$JOB_DIR/pipeline.log"
STATUS="$JOB_DIR/status.json"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"

mkdir -p "$JOB_DIR" "$OUTPUT_ROOT"

if [[ "${1:-}" == "status" ]]; then
  cat "$STATUS" 2>/dev/null || echo '{"state":"not_started"}'
  exit 0
fi

if [[ "${1:-}" == "stop" ]]; then
  if [[ -f "$PID_FILE" ]]; then
    pid="$(<"$PID_FILE")"
    kill "$pid" 2>/dev/null || true
  fi
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then exit 0; fi
  echo $$ > "$PID_FILE"
  trap 'rm -f "$PID_FILE"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  "$PYTHON_BIN" -m py_compile AviationDB/scripts/build_global_corridor_relay_network.py
  "$PYTHON_BIN" AviationDB/scripts/build_global_corridor_relay_network.py \
    --db /private/tmp/travel-globe-corridor-7d-v2/merge/corridor-merge.sqlite \
    --chains "$INPUT_ROOT/global-corridor-chains.json.gz" \
    --output "$OUTPUT_ROOT/global-corridor-relay-network.json.gz" \
    --geojson "$OUTPUT_ROOT/global-corridor-relay-network.geojson.gz" \
    --review-output "$OUTPUT_ROOT/global-corridor-relay-review.json" \
    --status "$JOB_DIR/status.json"
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
  echo "already running pid=$(<"$PID_FILE")"
  exit 0
fi
echo "Use launchd plist to start this worker: $ROOT/AviationDB/scripts/com.alien.travel-globe-global-relay-7d.plist"

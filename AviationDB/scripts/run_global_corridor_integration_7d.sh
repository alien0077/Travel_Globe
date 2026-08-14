#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-global-corridor-integration-7d"
GLOBAL_INPUT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-cross-continent-7d/global-cross-continent-corridors.json.gz"
ASIA_NA_INPUT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/asia-northamerica-7d/asia-northamerica-corridor.json.gz"
OUTPUT_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-corridor-network-7d"
STATUS="$JOB_DIR/status.json"
LOG="$JOB_DIR/pipeline.log"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"
LABEL="travel-globe-global-corridor-integration-7d"

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
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then exit 0; fi
  echo $$ > "$PID_FILE"
  trap 'rm -f "$PID_FILE"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  /usr/local/bin/python3 -m py_compile AviationDB/scripts/integrate_global_cross_continent_corridors_7d.py
  exec /usr/local/bin/python3 AviationDB/scripts/integrate_global_cross_continent_corridors_7d.py \
    --global-input "$GLOBAL_INPUT" \
    --asia-northamerica-input "$ASIA_NA_INPUT" \
    --output-root "$OUTPUT_ROOT" \
    --status "$STATUS"
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
  echo "already running pid=$(<"$PID_FILE")"
  exit 0
fi
/bin/launchctl remove "$LABEL" 2>/dev/null || true
/bin/launchctl submit -l "$LABEL" -- /bin/bash "$ROOT/AviationDB/scripts/run_global_corridor_integration_7d.sh" __worker
echo "started background pipeline label=$LABEL job_dir=$JOB_DIR log=$LOG status=$STATUS output=$OUTPUT_ROOT"

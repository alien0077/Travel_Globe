#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-global-network-assembly-7d"
BASE_GRAPH="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/corridor-7d-v2/global/global-corridor-graph.json.gz"
BASE_RELAY="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/corridor-7d-v2/global/relay-network/global-corridor-relay-network.json.gz"
CROSS_NETWORK="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-corridor-network-7d/global-corridor-network.json.gz"
OUTPUT_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d"
STATUS="$JOB_DIR/status.json"
LOG="$JOB_DIR/pipeline.log"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"
LABEL="travel-globe-global-network-assembly-7d-v2"

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
  /usr/local/bin/python3 -m py_compile AviationDB/scripts/assemble_global_corridor_network_7d.py
  exec /usr/local/bin/python3 AviationDB/scripts/assemble_global_corridor_network_7d.py \
    --base-graph "$BASE_GRAPH" \
    --base-relay "$BASE_RELAY" \
    --cross-network "$CROSS_NETWORK" \
    --output-root "$OUTPUT_ROOT" \
    --status "$STATUS"
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
  echo "already running pid=$(<"$PID_FILE")"
  exit 0
fi
/bin/launchctl remove "$LABEL" 2>/dev/null || true
/bin/launchctl submit -l "$LABEL" -- /bin/bash "$ROOT/AviationDB/scripts/run_global_network_assembly_7d.sh" __worker
echo "started background pipeline label=$LABEL job_dir=$JOB_DIR log=$LOG status=$STATUS output=$OUTPUT_ROOT"

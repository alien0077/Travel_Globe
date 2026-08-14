#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-global-025-completion"
STATUS="$JOB_DIR/status.json"
LOG="$JOB_DIR/pipeline.log"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"
LABEL="travel-globe-global-025-completion-v1"
CROSS_INPUT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-cross-continent-7d-025/global-cross-continent-corridors.json.gz"
CROSS_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-corridor-network-7d-025"
GLOBAL_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025"

mkdir -p "$JOB_DIR" "$CROSS_ROOT" "$GLOBAL_ROOT"

if [[ "${1:-}" == "status" ]]; then
  cat "$STATUS" 2>/dev/null || echo '{"state":"not_started"}'
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then exit 0; fi
  echo $$ > "$PID_FILE"
  trap 'rm -f "$PID_FILE"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  write_status() {
    /usr/local/bin/python3 - "$STATUS" "$1" "$2" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
path,state,phase=sys.argv[1:]
Path(path).write_text(json.dumps({"updatedAt":datetime.now(timezone.utc).isoformat(),"state":state,"phase":phase,"log":"/private/tmp/travel-globe-global-025-completion/pipeline.log"},ensure_ascii=False,indent=2)+"\n")
PY
  }
  write_status running integrate
  /usr/local/bin/python3 AviationDB/scripts/integrate_global_cross_continent_corridors_7d.py \
    --cross-all-input "$CROSS_INPUT" \
    --output-root "$CROSS_ROOT" \
    --status "$JOB_DIR/cross-status.json"
  write_status running assemble
  /usr/local/bin/python3 AviationDB/scripts/assemble_global_corridor_network_7d.py \
    --base-graph "$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/corridor-7d-v2/global/global-corridor-graph.json.gz" \
    --base-relay "$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/corridor-7d-v2/global/relay-network/global-corridor-relay-network.json.gz" \
    --cross-network "$CROSS_ROOT/global-corridor-network.json.gz" \
    --output-root "$GLOBAL_ROOT" \
    --status "$JOB_DIR/global-status.json"
  write_status running khh_validation
  /usr/local/bin/python3 AviationDB/scripts/validate_khh_global_network_7d.py \
    --network "$GLOBAL_ROOT/global-corridor-network.json.gz" \
    --airports "$ROOT/shared/offline-packs/core-global/airports-index.json" \
    --output "$GLOBAL_ROOT/khh-validation.json"
  write_status complete written
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
  echo "already running pid=$(<"$PID_FILE")"
  exit 0
fi
echo "Use launchctl submit with label $LABEL to start __worker"

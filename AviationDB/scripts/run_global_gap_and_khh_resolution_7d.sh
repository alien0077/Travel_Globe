#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-global-gap-khh-resolution-7d"
STATUS="$JOB_DIR/status.json"
LOG="$JOB_DIR/pipeline.log"
LOCK_DIR="$JOB_DIR/worker.lock"
PID_FILE="$JOB_DIR/pid"
LABEL="travel-globe-global-gap-khh-resolution-7d-v1"
DONE="$JOB_DIR/done.json"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"
NETWORK="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025/global-corridor-network.json.gz"
AIRPORTS="$ROOT/shared/offline-packs/core-global/airports-index.json"
RAW_ROOT="$ROOT/AviationDB/data/raw/adsblol"
OUTPUT_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025/resolution"

mkdir -p "$JOB_DIR" "$OUTPUT_ROOT"

if [[ "${1:-}" == "status" ]]; then
  cat "$STATUS" 2>/dev/null || printf '{"state":"not_started","jobDir":"%s"}\n' "$JOB_DIR"
  exit 0
fi

if [[ "${1:-}" != "__worker" ]] && [[ -s "$DONE" ]] && rg -q '"state": "complete"' "$DONE"; then
  printf '{"state":"already_complete","done":"%s"}\n' "$DONE"
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  if [[ -s "$DONE" ]] && rg -q '"state": "complete"' "$DONE"; then exit 0; fi
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then exit 0; fi
  echo "$$" > "$PID_FILE"
  trap 'rm -f "$PID_FILE"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  "$PYTHON_BIN" -m py_compile AviationDB/scripts/resolve_global_gap_and_khh_endpoints_7d.py
  "$PYTHON_BIN" AviationDB/scripts/resolve_global_gap_and_khh_endpoints_7d.py \
    --network "$NETWORK" \
    --airport-index "$AIRPORTS" \
    --raw-root "$RAW_ROOT" \
    --output-root "$OUTPUT_ROOT" \
    --status "$JOB_DIR/resolution-status.json"
  "$PYTHON_BIN" - "$STATUS" "$JOB_DIR" "$LOG" "$OUTPUT_ROOT" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

status, job_dir, log, output_root = sys.argv[1:]
payload = json.loads((Path(job_dir) / "resolution-status.json").read_text(encoding="utf-8"))
payload.update({"state": "complete", "updatedAt": datetime.now(timezone.utc).isoformat(), "jobDir": job_dir, "log": log, "outputRoot": output_root})
Path(status).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
Path(job_dir, "done.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
  launchctl remove "$LABEL" 2>/dev/null || true
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  printf '{"state":"already_running","pid":%s,"jobDir":"%s","log":"%s"}\n' "$(cat "$PID_FILE")" "$JOB_DIR" "$LOG"
  exit 0
fi

python3 - "$STATUS" "$JOB_DIR" "$LOG" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status, job_dir, log = sys.argv[1:]
Path(status).write_text(json.dumps({"state": "starting", "updatedAt": datetime.now(timezone.utc).isoformat(), "jobDir": job_dir, "log": log}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
launchctl remove "$LABEL" 2>/dev/null || true
launchctl submit -l "$LABEL" -- /bin/bash "$ROOT/AviationDB/scripts/run_global_gap_and_khh_resolution_7d.sh" __worker
printf '{"state":"started","launcher":"launchctl","label":"%s","jobDir":"%s","log":"%s","status":"%s"}\n' "$LABEL" "$JOB_DIR" "$LOG" "$STATUS"

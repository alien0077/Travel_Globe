#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-global-connectivity-audit-7d"
STATUS="$JOB_DIR/status.json"
LOG="$JOB_DIR/pipeline.log"
LOCK_DIR="$JOB_DIR/worker.lock"
PID_FILE="$JOB_DIR/pid"
LABEL="travel-globe-global-connectivity-audit-7d-v1"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"
NETWORK="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025/global-corridor-network.json.gz"
AIRPORTS="$ROOT/shared/offline-packs/core-global/airports-index.json"
OUTPUT_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025/connectivity"

mkdir -p "$JOB_DIR" "$OUTPUT_ROOT"

if [[ "${1:-}" == "status" ]]; then
  cat "$STATUS" 2>/dev/null || printf '{"state":"not_started","jobDir":"%s"}\n' "$JOB_DIR"
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    exit 0
  fi
  echo "$$" > "$PID_FILE"
  trap 'rm -f "$PID_FILE"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  "$PYTHON_BIN" -m py_compile AviationDB/scripts/audit_global_network_connectivity_7d.py
  "$PYTHON_BIN" AviationDB/scripts/audit_global_network_connectivity_7d.py \
    --network "$NETWORK" \
    --airports "$AIRPORTS" \
    --output-root "$OUTPUT_ROOT" \
    --status "$JOB_DIR/audit-status.json"
  "$PYTHON_BIN" - "$STATUS" "$JOB_DIR" "$LOG" "$OUTPUT_ROOT" <<'PY'
import json, sys
from datetime import datetime, timezone
from pathlib import Path

status, job_dir, log, output_root = sys.argv[1:]
audit_status = Path(job_dir) / "audit-status.json"
payload = json.loads(audit_status.read_text(encoding="utf-8"))
payload.update({"state": "complete", "updatedAt": datetime.now(timezone.utc).isoformat(), "jobDir": job_dir, "log": log, "outputRoot": output_root})
Path(status).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
Path(job_dir, "done.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
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
Path(status).write_text(json.dumps({"state":"starting","updatedAt":datetime.now(timezone.utc).isoformat(),"jobDir":job_dir,"log":log},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
PY
launchctl remove "$LABEL" 2>/dev/null || true
launchctl submit -l "$LABEL" -- /bin/bash "$ROOT/AviationDB/scripts/run_global_connectivity_audit_7d.sh" __worker
printf '{"state":"started","launcher":"launchctl","label":"%s","jobDir":"%s","log":"%s","status":"%s"}\n' "$LABEL" "$JOB_DIR" "$LOG" "$STATUS"

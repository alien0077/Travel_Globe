#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-observed-ifr-validation"
LOG="$JOB_DIR/pipeline.log"
STATUS="$JOB_DIR/status.json"
PID_FILE="$JOB_DIR/pid"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"
LABEL="travel-globe-observed-ifr-validation"

mkdir -p "$JOB_DIR"

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$STATUS" ]]; then
    cat "$STATUS"
  else
    printf '{"state":"not_started","jobDir":"%s","log":"%s"}\n' "$JOB_DIR" "$LOG"
  fi
  exit 0
fi

if [[ "${1:-}" == "stop" ]]; then
  launchctl remove "$LABEL" 2>/dev/null || true
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
  fi
  "$PYTHON_BIN" - "$STATUS" "$JOB_DIR" "$LOG" <<'PY'
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status, job_dir, log = sys.argv[1:4]
Path(status).write_text(json.dumps({
    "state": "stop_requested",
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "jobDir": job_dir,
    "log": log,
}, ensure_ascii=False) + "\n", encoding="utf-8")
PY
  cat "$STATUS"
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  echo "=== observed IFR validation started $(date -u +%FT%TZ) ==="
  "$PYTHON_BIN" -m py_compile AviationDB/scripts/validate_observed_routes_ifr.py
  "$PYTHON_BIN" AviationDB/scripts/validate_observed_routes_ifr.py \
    --status "$STATUS" \
    --progress-every 250
  echo "=== observed IFR validation completed $(date -u +%FT%TZ) ==="
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  printf '{"state":"already_running","pid":%s,"jobDir":"%s","log":"%s","status":"%s"}\n' "$(cat "$PID_FILE")" "$JOB_DIR" "$LOG" "$STATUS"
  exit 0
fi

printf '{"state":"starting","jobDir":"%s","log":"%s","status":"%s"}\n' "$JOB_DIR" "$LOG" "$STATUS" > "$STATUS"
if command -v launchctl >/dev/null 2>&1; then
  launchctl remove "$LABEL" 2>/dev/null || true
  launchctl submit -l "$LABEL" -- /bin/bash "$ROOT/AviationDB/scripts/run_observed_ifr_validation.sh" __worker
  printf '{"state":"started","launcher":"launchctl","label":"%s","jobDir":"%s","log":"%s","status":"%s"}\n' "$LABEL" "$JOB_DIR" "$LOG" "$STATUS"
else
  nohup /bin/bash "$ROOT/AviationDB/scripts/run_observed_ifr_validation.sh" __worker > "$LOG" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  printf '{"state":"started","launcher":"nohup","pid":%s,"jobDir":"%s","log":"%s","status":"%s"}\n' "$pid" "$JOB_DIR" "$LOG" "$STATUS"
fi

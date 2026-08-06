#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-observed-ifr-post-triage"
SOURCE_JOB_DIR="${SOURCE_JOB_DIR:-/private/tmp/travel-globe-observed-daily-ifr-21d}"
SOURCE_STATUS="$SOURCE_JOB_DIR/status.json"
INPUT_DIR="${INPUT_DIR:-$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/daily-ifr-21d}"
OUTPUT_DIR="${OUTPUT_DIR:-$INPUT_DIR/post-ifr-triage}"
LOG="$JOB_DIR/triage.log"
STATUS="$JOB_DIR/status.json"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"
LABEL="travel-globe-observed-ifr-post-triage"
WAIT_SECONDS="${WAIT_SECONDS:-300}"

mkdir -p "$JOB_DIR" "$OUTPUT_DIR"

write_status() {
  local state="$1"
  local phase="${2:-}"
  "$PYTHON_BIN" - "$STATUS" "$state" "$phase" "$JOB_DIR" "$LOG" "$INPUT_DIR" "$OUTPUT_DIR" <<'PY'
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status, state, phase, job_dir, log, input_dir, output_dir = sys.argv[1:8]
payload = {
    "state": state,
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "jobDir": job_dir,
    "log": log,
    "inputDir": input_dir,
    "outputDir": output_dir,
}
if phase:
    payload["phase"] = phase
Path(status).write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$STATUS" ]]; then
    cat "$STATUS"
  else
    printf '{"state":"not_started","jobDir":"%s","log":"%s","inputDir":"%s","outputDir":"%s"}\n' "$JOB_DIR" "$LOG" "$INPUT_DIR" "$OUTPUT_DIR"
  fi
  exit 0
fi

if [[ "${1:-}" == "stop" ]]; then
  launchctl remove "$LABEL" 2>/dev/null || true
  if [[ -f "$PID_FILE" ]]; then
    existing_pid="$(cat "$PID_FILE" 2>/dev/null || true)"
    if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
      kill "$existing_pid" 2>/dev/null || true
    fi
  fi
  pkill -f "triage_observed_ifr_validation.py.*post-ifr-triage" 2>/dev/null || true
  rmdir "$LOCK_DIR" 2>/dev/null || true
  write_status "stop_requested" "stop"
  cat "$STATUS"
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    echo "worker lock exists at $LOCK_DIR; another worker is probably running" >> "$LOG"
    write_status "already_running" "worker-lock"
    exit 0
  fi
  printf '%s\n' "$$" > "$PID_FILE"
  trap 'rm -f "$PID_FILE"; rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  echo "=== observed IFR post-triage worker started $(date -u +%FT%TZ) ==="
  "$PYTHON_BIN" -m py_compile AviationDB/scripts/triage_observed_ifr_validation.py

  last_validation_count=0
  while true; do
    source_state="$("$PYTHON_BIN" - "$SOURCE_STATUS" <<'PY'
from __future__ import annotations
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.exists():
    print("missing")
else:
    try:
        print(json.loads(path.read_text(encoding="utf-8")).get("state", "unknown"))
    except json.JSONDecodeError:
        print("invalid")
PY
)"
    if [[ "$source_state" == "complete" ]]; then
      break
    fi
    validation_count="$(find "$INPUT_DIR" -path '*/ifr-validation-dedup/observed-routes-ifr-validation.jsonl' -type f | wc -l | tr -d ' ')"
    if [[ "$validation_count" -gt "$last_validation_count" ]]; then
      write_status "running" "incremental-triage-$validation_count-days"
      echo "incremental triage for $validation_count completed validation days $(date -u +%FT%TZ)"
      "$PYTHON_BIN" AviationDB/scripts/triage_observed_ifr_validation.py \
        --input-dir "$INPUT_DIR" \
        --output-dir "$OUTPUT_DIR" \
        --status "$STATUS" \
        --progress-every 5000
      last_validation_count="$validation_count"
    fi
    write_status "waiting" "wait-source-$source_state"
    echo "waiting for source job complete: state=$source_state $(date -u +%FT%TZ)"
    sleep "$WAIT_SECONDS"
  done

  write_status "running" "triage"
  "$PYTHON_BIN" AviationDB/scripts/triage_observed_ifr_validation.py \
    --input-dir "$INPUT_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --status "$STATUS" \
    --progress-every 5000
  cp "$STATUS" "$JOB_DIR/done.json"
  echo "=== observed IFR post-triage worker completed $(date -u +%FT%TZ) ==="
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  printf '{"state":"already_running","pid":%s,"jobDir":"%s","log":"%s","inputDir":"%s","outputDir":"%s","status":"%s"}\n' "$(cat "$PID_FILE")" "$JOB_DIR" "$LOG" "$INPUT_DIR" "$OUTPUT_DIR" "$STATUS"
  exit 0
fi

write_status "starting" "launch"
if command -v launchctl >/dev/null 2>&1; then
  launchctl remove "$LABEL" 2>/dev/null || true
  launchctl submit -l "$LABEL" -- /bin/bash "$ROOT/AviationDB/scripts/run_observed_ifr_post_triage.sh" __worker
  printf '{"state":"started","launcher":"launchctl","label":"%s","jobDir":"%s","log":"%s","inputDir":"%s","outputDir":"%s","status":"%s"}\n' "$LABEL" "$JOB_DIR" "$LOG" "$INPUT_DIR" "$OUTPUT_DIR" "$STATUS"
else
  nohup /bin/bash "$ROOT/AviationDB/scripts/run_observed_ifr_post_triage.sh" __worker > "$LOG" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  printf '{"state":"started","launcher":"nohup","pid":%s,"jobDir":"%s","log":"%s","inputDir":"%s","outputDir":"%s","status":"%s"}\n' "$pid" "$JOB_DIR" "$LOG" "$INPUT_DIR" "$OUTPUT_DIR" "$STATUS"
fi

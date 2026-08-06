#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-observed-ifr-completion"
TRIAGE_STATUS="${TRIAGE_STATUS:-/private/tmp/travel-globe-observed-ifr-post-triage/status.json}"
DAILY_DIR="${DAILY_DIR:-$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/daily-ifr-21d}"
TRIAGE_DIR="${TRIAGE_DIR:-$DAILY_DIR/post-ifr-triage}"
OUTPUT_DIR="${OUTPUT_DIR:-$DAILY_DIR/post-ifr-completion}"
LOG="$JOB_DIR/completion.log"
STATUS="$JOB_DIR/status.json"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"
LABEL="travel-globe-observed-ifr-completion"

mkdir -p "$JOB_DIR" "$OUTPUT_DIR"

write_status() {
  local state="$1"
  local phase="${2:-}"
  "$PYTHON_BIN" - "$STATUS" "$state" "$phase" "$JOB_DIR" "$LOG" "$DAILY_DIR" "$TRIAGE_DIR" "$OUTPUT_DIR" <<'PY'
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status, state, phase, job_dir, log, daily_dir, triage_dir, output_dir = sys.argv[1:9]
payload = {
    "state": state,
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "jobDir": job_dir,
    "log": log,
    "dailyDir": daily_dir,
    "triageDir": triage_dir,
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
    printf '{"state":"not_started","jobDir":"%s","log":"%s","dailyDir":"%s","triageDir":"%s","outputDir":"%s"}\n' "$JOB_DIR" "$LOG" "$DAILY_DIR" "$TRIAGE_DIR" "$OUTPUT_DIR"
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
  pkill -f "complete_observed_ifr_triage.py.*post-ifr-completion" 2>/dev/null || true
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
  echo "=== observed IFR completion worker started $(date -u +%FT%TZ) ==="
  "$PYTHON_BIN" -m py_compile AviationDB/scripts/complete_observed_ifr_triage.py

  triage_state="$("$PYTHON_BIN" - "$TRIAGE_STATUS" <<'PY'
from __future__ import annotations
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
if not path.exists():
    print("missing")
else:
    print(json.loads(path.read_text(encoding="utf-8")).get("state", "unknown"))
PY
)"
  if [[ "$triage_state" != "complete" ]]; then
    write_status "blocked" "triage-not-complete-$triage_state"
    echo "triage status is not complete: $triage_state"
    exit 2
  fi

  write_status "running" "complete-queues"
  "$PYTHON_BIN" AviationDB/scripts/complete_observed_ifr_triage.py \
    --daily-dir "$DAILY_DIR" \
    --triage-dir "$TRIAGE_DIR" \
    --output-dir "$OUTPUT_DIR" \
    --status "$STATUS" \
    --progress-every 1000
  cp "$STATUS" "$JOB_DIR/done.json"
  echo "=== observed IFR completion worker completed $(date -u +%FT%TZ) ==="
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  printf '{"state":"already_running","pid":%s,"jobDir":"%s","log":"%s","status":"%s"}\n' "$(cat "$PID_FILE")" "$JOB_DIR" "$LOG" "$STATUS"
  exit 0
fi

write_status "starting" "launch"
if command -v launchctl >/dev/null 2>&1; then
  launchctl remove "$LABEL" 2>/dev/null || true
  launchctl submit -l "$LABEL" -- /bin/bash "$ROOT/AviationDB/scripts/run_observed_ifr_completion.sh" __worker
  printf '{"state":"started","launcher":"launchctl","label":"%s","jobDir":"%s","log":"%s","status":"%s","outputDir":"%s"}\n' "$LABEL" "$JOB_DIR" "$LOG" "$STATUS" "$OUTPUT_DIR"
else
  nohup /bin/bash "$ROOT/AviationDB/scripts/run_observed_ifr_completion.sh" __worker > "$LOG" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  printf '{"state":"started","launcher":"nohup","pid":%s,"jobDir":"%s","log":"%s","status":"%s","outputDir":"%s"}\n' "$pid" "$JOB_DIR" "$LOG" "$STATUS" "$OUTPUT_DIR"
fi

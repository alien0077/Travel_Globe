#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-corridor-7d-v2"
RAW_ROOT="$ROOT/AviationDB/data/raw/adsblol"
OUTPUT_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/corridor-7d-v2"
LOG="$JOB_DIR/pipeline.log"
STATUS="$JOB_DIR/status.json"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"

mkdir -p "$JOB_DIR"

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$STATUS" ]]; then cat "$STATUS"; else echo '{"state":"not_started"}'; fi
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

  write_status() {
    local state="$1"
    local phase="$2"
    "$PYTHON_BIN" - "$STATUS" "$state" "$phase" <<'PY'
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

path, state, phase = sys.argv[1:]
Path(path).write_text(json.dumps({
    "state": state,
    "phase": phase,
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "jobDir": "/private/tmp/travel-globe-corridor-7d-v2",
    "log": "/private/tmp/travel-globe-corridor-7d-v2/pipeline.log",
}, ensure_ascii=False) + "\n", encoding="utf-8")
PY
  }

  run_step() {
    local name="$1"
    shift
    write_status running "$name"
    echo "=== ${name} started $(date -u +%FT%TZ) ==="
    "$@"
    local rc=$?
    echo "=== ${name} exited status=${rc} $(date -u +%FT%TZ) ==="
    if [[ "$rc" -ne 0 ]]; then
      write_status failed "$name"
      exit "$rc"
    fi
  }

  mkdir -p "$OUTPUT_ROOT/global"
  write_status running preflight
  run_step raw_observation "$PYTHON_BIN" AviationDB/scripts/run_raw_corridor_7d.py \
    --job-dir "$JOB_DIR/raw" \
    --raw-root "$RAW_ROOT" \
    --output-root "$OUTPUT_ROOT" \
    --no-download
  run_step merge "$PYTHON_BIN" AviationDB/scripts/merge_corridor_7d.py \
    --job-dir "$JOB_DIR/merge" \
    --input-root "$OUTPUT_ROOT" \
    --output-root "$OUTPUT_ROOT/global"
  run_step chains "$PYTHON_BIN" AviationDB/scripts/build_global_corridor_chains.py \
    --db "$JOB_DIR/merge/corridor-merge.sqlite" \
    --output "$OUTPUT_ROOT/global/global-corridor-chains.json.gz"
  run_step bridges "$PYTHON_BIN" AviationDB/scripts/build_global_corridor_bridges.py \
    --db "$JOB_DIR/merge/corridor-merge.sqlite" \
    --chains "$OUTPUT_ROOT/global/global-corridor-chains.json.gz" \
    --output "$OUTPUT_ROOT/global/global-corridor-bridges.json.gz" \
    --status "$JOB_DIR/bridge-status.json"
  run_step evidence_index "$PYTHON_BIN" AviationDB/scripts/build_global_corridor_evidence_index.py \
    --db "$JOB_DIR/merge/corridor-merge.sqlite" \
    --chains "$OUTPUT_ROOT/global/global-corridor-chains.json.gz" \
    --bridges "$OUTPUT_ROOT/global/global-corridor-bridges.json.gz" \
    --output "$OUTPUT_ROOT/global/evidence-index.json.gz" \
    --review-output "$OUTPUT_ROOT/global/global-corridor-bridge-review.json"
  write_status complete all_stages
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(<"$PID_FILE")" 2>/dev/null; then
  echo "already running pid=$(<"$PID_FILE")"
  exit 0
fi

launchctl remove travel-globe-global-corridor-7d-v2 2>/dev/null || true
launchctl submit -l travel-globe-global-corridor-7d-v2 -- /bin/bash "$ROOT/AviationDB/scripts/run_global_corridor_7d_v2.sh" __worker
echo "started launchctl job_dir=$JOB_DIR log=$LOG status=$STATUS"

#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-global-route-shapes"
LOG="$JOB_DIR/pipeline.log"
STATUS="$JOB_DIR/status.json"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"

mkdir -p "$JOB_DIR"

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$STATUS" ]]; then
    cat "$STATUS"
  else
    printf '{"state":"not_started","jobDir":"%s"}\n' "$JOB_DIR"
  fi
  exit 0
fi

if [[ "${1:-}" == "stop" ]]; then
  pkill -f "select_global_route_shapes.py" 2>/dev/null || true
  printf '{"state":"stop_requested","updatedAt":"%s","jobDir":"%s","log":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" > "$STATUS"
  cat "$STATUS"
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  exec >> "$LOG" 2>&1
  printf '{"state":"running","updatedAt":"%s","jobDir":"%s","log":"%s","python":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" "$PYTHON_BIN" > "$STATUS"
  cd "$ROOT"
  echo "=== global route shapes started $(date -u +%FT%TZ) ==="
  "$PYTHON_BIN" -m py_compile AviationDB/scripts/select_pair_route_shape.py AviationDB/scripts/select_global_route_shapes.py
  "$PYTHON_BIN" AviationDB/scripts/select_global_route_shapes.py --status "$STATUS"
  echo "=== global route shapes completed $(date -u +%FT%TZ) ==="
  exit 0
fi

printf '{"state":"launcher_only","hint":"Use launchctl submit with __worker.","jobDir":"%s","log":"%s","status":"%s"}\n' "$JOB_DIR" "$LOG" "$STATUS"

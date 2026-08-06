#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-global-route-shapes"
LOG="$JOB_DIR/pipeline.log"
STATUS="$JOB_DIR/status.json"
LOCK_DIR="$JOB_DIR/run.lock"
DONE="$JOB_DIR/done.json"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"

mkdir -p "$JOB_DIR"

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$STATUS" ]]; then
    cat "$STATUS"
  elif [[ -f "$DONE" ]]; then
    cat "$DONE"
  else
    printf '{"state":"not_started","jobDir":"%s"}\n' "$JOB_DIR"
  fi
  exit 0
fi

if [[ "${1:-}" == "stop" ]]; then
  launchctl remove travel-globe-global-route-shapes 2>/dev/null || true
  pkill -f "select_global_route_shapes.py" 2>/dev/null || true
  printf '{"state":"stop_requested","updatedAt":"%s","jobDir":"%s","log":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" > "$STATUS"
  cat "$STATUS"
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  exec >> "$LOG" 2>&1
  if [[ "${FORCE_GLOBAL_ROUTE_SHAPES:-0}" != "1" && -f "$DONE" ]]; then
    cp "$DONE" "$STATUS"
    echo "=== global route shapes skipped: completed marker exists $(date -u +%FT%TZ) ==="
    exit 0
  fi
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    existing_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
      printf '{"state":"already_running","updatedAt":"%s","jobDir":"%s","log":"%s","pid":%s}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" "$existing_pid" > "$STATUS"
      echo "=== global route shapes skipped: worker already running pid=$existing_pid $(date -u +%FT%TZ) ==="
      exit 0
    fi
    echo "=== global route shapes removing stale lock pid=$existing_pid $(date -u +%FT%TZ) ==="
    rm -f "$LOCK_DIR/pid" 2>/dev/null || true
    rmdir "$LOCK_DIR" 2>/dev/null || true
    if ! mkdir "$LOCK_DIR" 2>/dev/null; then
      printf '{"state":"lock_busy","updatedAt":"%s","jobDir":"%s","log":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" > "$STATUS"
      exit 0
    fi
  fi
  echo "$$" > "$LOCK_DIR/pid"
  cleanup_lock() {
    rm -f "$LOCK_DIR/pid" 2>/dev/null || true
    rmdir "$LOCK_DIR" 2>/dev/null || true
  }
  trap cleanup_lock EXIT
  printf '{"state":"running","updatedAt":"%s","jobDir":"%s","log":"%s","python":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" "$PYTHON_BIN" > "$STATUS"
  cd "$ROOT"
  echo "=== global route shapes started $(date -u +%FT%TZ) ==="
  "$PYTHON_BIN" -m py_compile AviationDB/scripts/select_pair_route_shape.py AviationDB/scripts/select_global_route_shapes.py
  "$PYTHON_BIN" AviationDB/scripts/select_global_route_shapes.py --status "$STATUS"
  cp "$STATUS" "$DONE"
  echo "=== global route shapes completed $(date -u +%FT%TZ) ==="
  exit 0
fi

printf '{"state":"launcher_only","hint":"Use launchctl submit with __worker. Set FORCE_GLOBAL_ROUTE_SHAPES=1 to rebuild after completion.","jobDir":"%s","log":"%s","status":"%s"}\n' "$JOB_DIR" "$LOG" "$STATUS"

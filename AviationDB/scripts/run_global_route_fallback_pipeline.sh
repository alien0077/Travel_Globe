#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-global-route-fallback"
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
  pkill -f "run_global_route_fallback_pipeline.sh __worker" 2>/dev/null || true
  printf '{"state":"stop_requested","stoppedAt":"%s","jobDir":"%s","log":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" > "$STATUS"
  cat "$STATUS"
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  exec >> "$LOG" 2>&1
  printf '{"state":"running","startedAt":"%s","jobDir":"%s","log":"%s","python":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" "$PYTHON_BIN" > "$STATUS"
  cd "$ROOT"

  run_step() {
    local name="$1"
    shift
    echo "=== ${name} started $(date -u +%FT%TZ) ==="
    "$@"
    local rc=$?
    echo "=== ${name} exited status=${rc} $(date -u +%FT%TZ) ==="
    if [[ "$rc" -ne 0 ]]; then
      printf '{"state":"failed","failedAt":"%s","failedStep":"%s","exitCode":%s,"jobDir":"%s","log":"%s"}\n' "$(date -u +%FT%TZ)" "$name" "$rc" "$JOB_DIR" "$LOG" > "$STATUS"
      exit "$rc"
    fi
  }

  run_step py_compile "$PYTHON_BIN" -m py_compile AviationDB/scripts/build_route_source_fusion.py AviationDB/scripts/export_route_fallback_pack.py
  run_step pytest "$PYTHON_BIN" -m pytest AviationDB/tests/test_route_source_fusion.py AviationDB/tests/test_route_fallback_pack.py AviationDB/tests/test_observed_routes.py
  run_step build_route_source_fusion "$PYTHON_BIN" AviationDB/scripts/build_route_source_fusion.py
  run_step export_route_fallback_pack "$PYTHON_BIN" AviationDB/scripts/export_route_fallback_pack.py
  run_step summarize "$PYTHON_BIN" - <<'PY'
import json
from pathlib import Path
manifest = json.loads(Path("shared/offline-packs/route-fallback/manifest.json").read_text(encoding="utf-8"))
print(json.dumps({"routeFallbackManifest": manifest["summary"], "bytes": manifest["bytes"]}, ensure_ascii=False, indent=2))
PY
  printf '{"state":"complete","completedAt":"%s","jobDir":"%s","log":"%s","python":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" "$PYTHON_BIN" > "$STATUS"
  exit 0
fi

printf '{"state":"launcher_only","hint":"Start this script with launchctl or run __worker in a detached shell.","jobDir":"%s","log":"%s","status":"%s"}\n' "$JOB_DIR" "$LOG" "$STATUS"

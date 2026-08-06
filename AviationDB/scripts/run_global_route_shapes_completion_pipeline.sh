#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-global-route-shapes-completion"
LOG="$JOB_DIR/pipeline.log"
STATUS="$JOB_DIR/status.json"
PID_FILE="$JOB_DIR/pid"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"

mkdir -p "$JOB_DIR"

write_status() {
  local state="$1"
  local step="${2:-}"
  "$PYTHON_BIN" - "$STATUS" "$state" "$step" "$JOB_DIR" "$LOG" <<'PY'
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status, state, step, job_dir, log = sys.argv[1:6]
payload = {
    "state": state,
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "jobDir": job_dir,
    "log": log,
}
if step:
    payload["step"] = step
Path(status).write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

summarize_pack() {
  local label="$1"
  local path="$2"
  "$PYTHON_BIN" - "$label" "$path" <<'PY'
from __future__ import annotations

import gzip
import json
import os
import sys

label, path = sys.argv[1:3]
if not os.path.exists(path):
    print(json.dumps({"label": label, "path": path, "exists": False}, ensure_ascii=False))
    raise SystemExit(0)
with gzip.open(path, "rt", encoding="utf-8") as handle:
    pack = json.load(handle)
print(json.dumps({
    "label": label,
    "path": path,
    "exists": True,
    "mtime": os.path.getmtime(path),
    "bytes": os.path.getsize(path),
    "generatedAt": pack.get("generatedAt"),
    "summary": pack.get("summary"),
}, ensure_ascii=False))
PY
}

run_step() {
  local name="$1"
  shift
  write_status "running" "$name"
  echo "=== step started: $name $(date -u +%FT%TZ) ==="
  "$@"
  echo "=== step completed: $name $(date -u +%FT%TZ) ==="
}

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$STATUS" ]]; then
    cat "$STATUS"
  else
    printf '{"state":"not_started","jobDir":"%s","log":"%s"}\n' "$JOB_DIR" "$LOG"
  fi
  exit 0
fi

if [[ "${1:-}" == "stop" ]]; then
  launchctl remove travel-globe-global-route-shapes-completion 2>/dev/null || true
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")" 2>/dev/null || true
    write_status "stop_requested" "stop"
  elif [[ -f "$STATUS" ]]; then
    cat "$STATUS"
    exit 0
  else
    write_status "stop_requested" "stop"
  fi
  cat "$STATUS"
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  echo "=== global route-shapes completion started $(date -u +%FT%TZ) ==="
  write_status "running" "startup"

  run_step "1-audit-before" summarize_pack "release-before" "AviationDB/data/releases/private/route-shapes/global.route-shapes.json.gz"

  run_step "4-build-route-source-fusion" "$PYTHON_BIN" AviationDB/scripts/build_route_source_fusion.py
  run_step "4-export-route-fallback-pack" "$PYTHON_BIN" AviationDB/scripts/export_route_fallback_pack.py

  run_step "1-and-4-force-directed-global-route-shapes" "$PYTHON_BIN" AviationDB/scripts/select_global_route_shapes.py \
    --status "$STATUS" \
    --progress-every 250

  run_step "2-diagnose-unavailable-before-recovery" "$PYTHON_BIN" AviationDB/scripts/diagnose_route_unavailable.py
  run_step "2-recover-selector-constraint-unavailable" "$PYTHON_BIN" AviationDB/scripts/recover_route_unavailable_shapes.py
  run_step "3-diagnose-unavailable-final" "$PYTHON_BIN" AviationDB/scripts/diagnose_route_unavailable.py
  run_step "3-export-runtime-route-shapes" "$PYTHON_BIN" AviationDB/scripts/export_route_shapes_runtime_pack.py

  run_step "1-audit-after" summarize_pack "release-after" "AviationDB/data/releases/private/route-shapes/global.route-shapes.json.gz"

  "$PYTHON_BIN" - "$STATUS" "$JOB_DIR" "$LOG" <<'PY'
from __future__ import annotations

import gzip
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

status, job_dir, log = sys.argv[1:4]
pack_path = Path("AviationDB/data/releases/private/route-shapes/global.route-shapes.json.gz")
diagnostics_path = Path("AviationDB/data/releases/private/route-shapes/route-unavailable-diagnostics.json")
with gzip.open(pack_path, "rt", encoding="utf-8") as handle:
    pack = json.load(handle)
diagnostics = json.loads(diagnostics_path.read_text(encoding="utf-8")) if diagnostics_path.exists() else {}
payload = {
    "state": "complete",
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "jobDir": job_dir,
    "log": log,
    "completedPack": str(pack_path),
    "summary": pack.get("summary"),
    "unavailableDiagnostics": diagnostics.get("summary"),
}
Path(status).write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
Path(job_dir, "done.json").write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
PY
  echo "=== global route-shapes completion finished $(date -u +%FT%TZ) ==="
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  printf '{"state":"already_running","pid":%s,"jobDir":"%s","log":"%s","status":"%s"}\n' "$(cat "$PID_FILE")" "$JOB_DIR" "$LOG" "$STATUS"
  exit 0
fi

write_status "starting" "launch"
if command -v launchctl >/dev/null 2>&1; then
  launchctl remove travel-globe-global-route-shapes-completion 2>/dev/null || true
  launchctl submit -l travel-globe-global-route-shapes-completion -- /bin/bash "$ROOT/AviationDB/scripts/run_global_route_shapes_completion_pipeline.sh" __worker
  printf '{"state":"started","launcher":"launchctl","label":"travel-globe-global-route-shapes-completion","jobDir":"%s","log":"%s","status":"%s"}\n' "$JOB_DIR" "$LOG" "$STATUS"
else
  nohup /bin/bash "$ROOT/AviationDB/scripts/run_global_route_shapes_completion_pipeline.sh" __worker > "$LOG" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  printf '{"state":"started","launcher":"nohup","pid":%s,"jobDir":"%s","log":"%s","status":"%s"}\n' "$pid" "$JOB_DIR" "$LOG" "$STATUS"
fi

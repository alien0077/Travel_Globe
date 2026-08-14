#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-endpoint-distance-repair-20260729-v2"
RAW_DIR="$ROOT/AviationDB/data/raw/adsblol/2026-07-29"
OUTPUT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/corridor-7d-v2-repaired-2026-08-01-v5/2026-07-29/endpoint-candidates.json.gz"
STATUS="$JOB_DIR/status.json"
DONE="$JOB_DIR/done.json"
FAILED="$JOB_DIR/failed.json"
LOCK="$JOB_DIR/worker.lock"
LOG="$JOB_DIR/worker.log"

mkdir -p "$JOB_DIR"

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$DONE" ]]; then cat "$DONE"; elif [[ -f "$FAILED" ]]; then cat "$FAILED"; elif [[ -f "$STATUS" ]]; then cat "$STATUS"; else echo '{"state":"not_started"}'; fi
  exit 0
fi

if [[ -f "$DONE" || -f "$FAILED" ]]; then
  echo "job already terminal; use a new versioned job root to rerun" >&2
  exit 2
fi

if [[ "${1:-}" == "__worker" ]]; then
  if ! mkdir "$LOCK" 2>/dev/null; then
    echo "worker already running: $LOCK" >&2
    exit 0
  fi
  trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  python3 -c 'import json,sys; from datetime import datetime,timezone; from pathlib import Path; Path(sys.argv[1]).write_text(json.dumps({"state":"running","phase":"endpoint_reparse_2026-07-29","updatedAt":datetime.now(timezone.utc).isoformat()})+"\n")' "$STATUS"
  set +e
  python3 "$ROOT/AviationDB/scripts/reparse_endpoint_candidates_day.py" --date 2026-07-29 --raw-dir "$RAW_DIR" --output "$OUTPUT" --endpoint-max-km 150
  rc=$?
  set -e
  if [[ "$rc" -eq 0 ]]; then
    python3 -c 'import json,sys; from datetime import datetime,timezone; from pathlib import Path; p={"state":"complete","phase":"endpoint_reparsed_2026-07-29","endpointMaxKm":150,"output":sys.argv[3],"updatedAt":datetime.now(timezone.utc).isoformat()}; Path(sys.argv[1]).write_text(json.dumps(p,ensure_ascii=False,indent=2)+"\n"); Path(sys.argv[2]).write_text(json.dumps(p,ensure_ascii=False)+"\n")' "$DONE" "$STATUS" "$OUTPUT"
  else
    python3 -c 'import json,sys; from datetime import datetime,timezone; from pathlib import Path; p={"state":"failed","phase":"endpoint_reparse_2026-07-29","exitCode":int(sys.argv[3]),"updatedAt":datetime.now(timezone.utc).isoformat()}; Path(sys.argv[1]).write_text(json.dumps(p,ensure_ascii=False,indent=2)+"\n"); Path(sys.argv[2]).write_text(json.dumps(p,ensure_ascii=False)+"\n")' "$FAILED" "$STATUS" "$rc"
    exit "$rc"
  fi
  exit 0
fi

nohup /bin/bash "$ROOT/AviationDB/scripts/run_endpoint_distance_repair_20260729.sh" __worker >/dev/null 2>&1 &
echo "started job_dir=$JOB_DIR log=$LOG status=$STATUS"

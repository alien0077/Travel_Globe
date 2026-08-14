#!/bin/bash
set -euo pipefail

ROOT="/Users/alien/Desktop/Travel_Globe"
JOB_DIR="/private/tmp/travel-globe-asia-northamerica-7d"
RAW_ROOT="$ROOT/AviationDB/data/raw/adsblol"
OUTPUT_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/asia-northamerica-7d"
STATUS="$JOB_DIR/status.json"
LOG="$JOB_DIR/worker.log"
LOCK="$JOB_DIR/worker.lock"

mkdir -p "$JOB_DIR"

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$STATUS" ]]; then
    /bin/cat "$STATUS"
  else
    /bin/echo '{"state":"not_started"}'
  fi
  exit 0
fi

if [[ "${1:-}" != "__worker" ]]; then
  exec /bin/bash "$0" __worker >>"$LOG" 2>&1
fi

if ! /bin/mkdir "$LOCK" 2>/dev/null; then
  /bin/echo "already running" >&2
  exit 0
fi
trap '/bin/rmdir "$LOCK" 2>/dev/null || true' EXIT

/usr/bin/python3 "$ROOT/AviationDB/scripts/extract_asia_northamerica_corridors_7d.py" \
  --raw-root "$RAW_ROOT" \
  --output-root "$OUTPUT_ROOT" \
  --status "$STATUS"

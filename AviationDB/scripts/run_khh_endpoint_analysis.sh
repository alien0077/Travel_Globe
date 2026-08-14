#!/bin/zsh
set -u

ROOT="/Users/alien/Desktop/Travel_Globe"
RAW_DIR="$ROOT/AviationDB/data/raw/adsblol"
RAW_RELEASE_DIR="$RAW_DIR/2026-08-02"
STATUS="$RAW_DIR/2026-08-02.analysis-status.json"
LOG="$RAW_DIR/2026-08-02.analysis.log"
OUTPUT_DIR="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/diagnostics"
PYTHON="/Library/Frameworks/Python.framework/Versions/3.14/bin/python3"

write_status() {
  "$PYTHON" - "$1" "$2" "$STATUS" <<'PY'
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

state, detail, path = sys.argv[1:]
Path(path).write_text(
    json.dumps(
        {"state": state, "updatedAt": datetime.now(UTC).isoformat(), "detail": detail},
        ensure_ascii=False,
    )
    + "\n",
    encoding="utf-8",
)
PY
}

mkdir -p "$RAW_DIR" "$OUTPUT_DIR"
write_status running "KHH endpoint recovery scan for 2026-08-02 started; raw files are retained."

cd "$ROOT" || exit 1
"$PYTHON" AviationDB/scripts/scan_khh_endpoint_recovery.py \
  --date 2026-08-02 \
  --year 2026 \
  --airport KHH \
  --work-dir "$RAW_DIR" \
  --output-dir "$OUTPUT_DIR" \
  >> "$LOG" 2>&1
rc=$?

if [[ "$rc" -eq 0 ]]; then
  write_status complete "KHH endpoint recovery scan completed; raw files were retained."
else
  write_status failed "KHH endpoint recovery scan failed with exit code $rc; raw files were retained."
fi
exit "$rc"

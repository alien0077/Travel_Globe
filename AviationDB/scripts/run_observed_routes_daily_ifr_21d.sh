#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-observed-daily-ifr-21d"
DOWNLOAD_DIR="$JOB_DIR/downloads"
OUTPUT_DIR="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/daily-ifr-21d"
LOG="$JOB_DIR/pipeline.log"
STATUS="$JOB_DIR/status.json"
PID_FILE="$JOB_DIR/pid"
LOCK_DIR="$JOB_DIR/worker.lock"
TRACE_INDEX="$JOB_DIR/seen-traces.sha1"
ROUTE_INDEX="$JOB_DIR/seen-route-fingerprints.tsv"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"
YEAR="${YEAR:-2026}"
DAYS="${DAYS:-21}"
START_DATE="${START_DATE:-}"
END_DATE="${END_DATE:-}"
MIN_PREFETCH_FREE_GIB="${MIN_PREFETCH_FREE_GIB:-8}"
LABEL="travel-globe-observed-daily-ifr-21d"

mkdir -p "$JOB_DIR" "$DOWNLOAD_DIR" "$OUTPUT_DIR"

write_status() {
  local state="$1"
  local phase="${2:-}"
  local date_value="${3:-}"
  local index_value="${4:-}"
  "$PYTHON_BIN" - "$STATUS" "$state" "$phase" "$date_value" "$index_value" "$JOB_DIR" "$LOG" "$OUTPUT_DIR" <<'PY'
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path
status, state, phase, date_value, index_value, job_dir, log, output_dir = sys.argv[1:9]
payload = {
    "state": state,
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "jobDir": job_dir,
    "log": log,
    "outputDir": output_dir,
}
if phase:
    payload["phase"] = phase
if date_value:
    payload["date"] = date_value
if index_value:
    payload["dayIndex"] = int(index_value)
Path(status).write_text(json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
PY
}

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$STATUS" ]]; then
    cat "$STATUS"
  else
    printf '{"state":"not_started","jobDir":"%s","log":"%s","outputDir":"%s"}\n' "$JOB_DIR" "$LOG" "$OUTPUT_DIR"
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
  pkill -f "build_observed_routes_range.py.*daily-ifr-21d" 2>/dev/null || true
  pkill -f "validate_observed_routes_ifr.py.*daily-ifr-21d" 2>/dev/null || true
  pkill -f "prefetch_adsblol_release.py.*travel-globe-observed-daily-ifr-21d" 2>/dev/null || true
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
  echo "=== daily observed ADS-B IFR pipeline started $(date -u +%FT%TZ) ==="
  write_status "running" "resolve-dates"
  "$PYTHON_BIN" -m py_compile \
    AviationDB/scripts/build_observed_routes_range.py \
    AviationDB/scripts/validate_observed_routes_ifr.py \
    AviationDB/scripts/filter_observed_routes_by_fingerprint.py \
    AviationDB/scripts/prefetch_adsblol_release.py

  DATES=()
  while IFS= read -r release_date; do
    [[ -n "$release_date" ]] && DATES+=("$release_date")
  done < <("$PYTHON_BIN" - "$YEAR" "$DAYS" "$OUTPUT_DIR" "$START_DATE" "$END_DATE" <<'PY'
from __future__ import annotations
import sys
from pathlib import Path
root = Path.cwd()
sys.path.insert(0, str(root / "AviationDB" / "src"))
from aviationdb.observed_routes import fetch_preferred_releases
year = int(sys.argv[1])
days = int(sys.argv[2])
output_dir = Path(sys.argv[3])
start_date = sys.argv[4].strip()
end_date = sys.argv[5].strip()
releases = fetch_preferred_releases(year)
existing_dates = sorted(
    item.name
    for item in output_dir.iterdir()
    if item.is_dir() and item.name in releases
) if output_dir.exists() else []
all_dates = sorted(releases)
if start_date:
    if start_date not in releases:
        raise SystemExit(f"START_DATE {start_date} is not in preferred releases")
    start_index = all_dates.index(start_date)
    selected = all_dates[start_index : start_index + days]
elif end_date:
    if end_date not in releases:
        raise SystemExit(f"END_DATE {end_date} is not in preferred releases")
    end_index = all_dates.index(end_date) + 1
    selected = all_dates[max(0, end_index - days) : end_index]
elif existing_dates:
    start_index = all_dates.index(existing_dates[0])
    selected = all_dates[start_index : start_index + days]
else:
    selected = all_dates[-days:]
for date in selected:
    print(date)
PY
)
  printf '%s\n' "${DATES[@]}" > "$JOB_DIR/dates.txt"
  echo "selected dates: ${DATES[*]}"

  day_count="${#DATES[@]}"
  index=0
  prefetch_pid=""
  prefetch_date=""
  for release_date in "${DATES[@]}"; do
    index=$((index + 1))
    day_dir="$OUTPUT_DIR/$release_date"
    mkdir -p "$day_dir"
    observed="$day_dir/observed-routes.$release_date.json.gz"
    filtered_observed="$day_dir/observed-routes.$release_date.dedup.json.gz"
    fingerprint_report="$day_dir/route-fingerprint-filter.$release_date.json"
    validation_dir="$day_dir/ifr-validation-dedup"
    day_status="$validation_dir/status.json"
    new_trace_index="$day_dir/new-traces.$release_date.sha1"
    new_route_index="$day_dir/new-route-fingerprints.$release_date.tsv"
    legacy_validation_summary="$day_dir/ifr-validation/observed-routes-ifr-validation-summary.json"
    validation_summary="$validation_dir/observed-routes-ifr-validation-summary.json"

    if [[ -n "$prefetch_pid" && "$prefetch_date" == "$release_date" ]]; then
      write_status "running" "wait-prefetch" "$release_date" "$index"
      echo "=== [$index/$day_count] waiting for prefetched raw $release_date pid=$prefetch_pid $(date -u +%FT%TZ) ==="
      wait "$prefetch_pid"
      prefetch_pid=""
      prefetch_date=""
    fi

    if [[ -s "$validation_summary" || -s "$legacy_validation_summary" ]]; then
      echo "=== [$index/$day_count] skip completed validation $release_date ==="
      continue
    fi

    write_status "running" "download-build-observed-audit" "$release_date" "$index"
    echo "=== [$index/$day_count] build observed audit routes $release_date $(date -u +%FT%TZ) ==="
    release_download_dir="$DOWNLOAD_DIR/$release_date"
    if [[ -s "$observed" && -s "$new_trace_index" ]]; then
      echo "=== [$index/$day_count] reuse existing observed audit routes $release_date: $observed ==="
    else
      "$PYTHON_BIN" AviationDB/scripts/build_observed_routes_range.py \
        --year "$YEAR" \
        --start-date "$release_date" \
        --days 1 \
        --work-dir "$DOWNLOAD_DIR" \
        --output "$observed" \
        --min-points 2 \
        --min-route-km 1 \
        --max-airport-km 650 \
        --max-track-detour-ratio 20 \
        --simplify-tolerance-km 1 \
        --max-points-per-route 256 \
        --seen-trace-index "$TRACE_INDEX" \
        --write-new-trace-index "$new_trace_index"
    fi

    write_status "running" "filter-route-fingerprints" "$release_date" "$index"
    echo "=== [$index/$day_count] filter observed route fingerprints $release_date $(date -u +%FT%TZ) ==="
    "$PYTHON_BIN" AviationDB/scripts/filter_observed_routes_by_fingerprint.py \
      --observed "$observed" \
      --output "$filtered_observed" \
      --seen-index "$ROUTE_INDEX" \
      --write-new-index "$new_route_index" \
      --report "$fingerprint_report" \
      --fingerprint-mode pair

    next_index=$((index + 1))
    if [[ -z "$prefetch_pid" && "$next_index" -le "$day_count" ]]; then
      next_date="${DATES[$((next_index - 1))]}"
      next_dir="$OUTPUT_DIR/$next_date"
      next_observed="$next_dir/observed-routes.$next_date.json.gz"
      next_release_download_dir="$DOWNLOAD_DIR/$next_date"
      free_kib="$(df -Pk "$DOWNLOAD_DIR" | awk 'NR==2 {print $4}')"
      min_prefetch_free_kib=$((MIN_PREFETCH_FREE_GIB * 1024 * 1024))
      if [[ ! -s "$next_observed" && "$free_kib" -lt "$min_prefetch_free_kib" ]]; then
        echo "=== [$index/$day_count] skip prefetch $next_date: free ${free_kib} KiB < required ${min_prefetch_free_kib} KiB ==="
      elif [[ ! -s "$next_observed" ]]; then
        write_status "running" "prefetch-next-raw" "$next_date" "$next_index"
        echo "=== [$index/$day_count] prefetch next raw $next_date while validating $release_date $(date -u +%FT%TZ) ==="
        "$PYTHON_BIN" AviationDB/scripts/prefetch_adsblol_release.py \
          --year "$YEAR" \
          --date "$next_date" \
          --work-dir "$DOWNLOAD_DIR" \
          --status "$JOB_DIR/prefetch-$next_date.status.json" &
        prefetch_pid="$!"
        prefetch_date="$next_date"
      elif [[ -d "$next_release_download_dir" ]]; then
        echo "=== [$index/$day_count] next raw/output already present for $next_date; skip prefetch ==="
      fi
    fi

    write_status "running" "ifr-validate-observed" "$release_date" "$index"
    echo "=== [$index/$day_count] IFR validate observed routes $release_date $(date -u +%FT%TZ) ==="
    "$PYTHON_BIN" AviationDB/scripts/validate_observed_routes_ifr.py \
      --observed "$filtered_observed" \
      --output-dir "$validation_dir" \
      --status "$day_status" \
      --progress-every 250 \
      --resume-existing

    write_status "running" "commit-route-fingerprint-index" "$release_date" "$index"
    "$PYTHON_BIN" - "$ROUTE_INDEX" "$new_route_index" "$release_date" "$index" "$day_count" "$JOB_DIR/route-index-progress.jsonl" <<'PY'
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path

seen_path = Path(sys.argv[1])
new_path = Path(sys.argv[2])
date = sys.argv[3]
index = int(sys.argv[4])
total = int(sys.argv[5])
progress_path = Path(sys.argv[6])

seen_path.parent.mkdir(parents=True, exist_ok=True)
seen = set()
if seen_path.exists():
    seen = {line.strip() for line in seen_path.read_text(encoding="utf-8").splitlines() if line.strip()}
new_keys = []
if new_path.exists():
    for line in new_path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if value and value not in seen:
            seen.add(value)
            new_keys.append(value)
tmp = seen_path.with_suffix(".tsv.tmp")
tmp.write_text("\n".join(sorted(seen)) + ("\n" if seen else ""), encoding="utf-8")
tmp.replace(seen_path)
row = {
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "date": date,
    "dayIndex": index,
    "days": total,
    "newRouteFingerprints": len(new_keys),
    "seenRouteFingerprints": len(seen),
    "routeIndex": str(seen_path),
}
with progress_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
print(json.dumps(row, ensure_ascii=False))
PY

    write_status "running" "commit-trace-diff-index" "$release_date" "$index"
    "$PYTHON_BIN" - "$TRACE_INDEX" "$new_trace_index" "$release_date" "$index" "$day_count" "$JOB_DIR/trace-index-progress.jsonl" <<'PY'
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path

seen_path = Path(sys.argv[1])
new_path = Path(sys.argv[2])
date = sys.argv[3]
index = int(sys.argv[4])
total = int(sys.argv[5])
progress_path = Path(sys.argv[6])

seen_path.parent.mkdir(parents=True, exist_ok=True)
seen = set()
if seen_path.exists():
    seen = {line.strip().lower() for line in seen_path.read_text(encoding="utf-8").splitlines() if line.strip()}
new_hashes = []
if new_path.exists():
    for line in new_path.read_text(encoding="utf-8").splitlines():
        value = line.strip().lower()
        if value and value not in seen:
            seen.add(value)
            new_hashes.append(value)
tmp = seen_path.with_suffix(".sha1.tmp")
tmp.write_text("\n".join(sorted(seen)) + ("\n" if seen else ""), encoding="utf-8")
tmp.replace(seen_path)
row = {
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "date": date,
    "dayIndex": index,
    "days": total,
    "newTraceHashes": len(new_hashes),
    "seenTraceHashes": len(seen),
    "traceIndex": str(seen_path),
}
with progress_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
print(json.dumps(row, ensure_ascii=False))
PY

    "$PYTHON_BIN" - "$release_date" "$index" "$day_count" "$observed" "$filtered_observed" "$fingerprint_report" "$validation_dir/observed-routes-ifr-validation-summary.json" "$new_trace_index" "$TRACE_INDEX" "$ROUTE_INDEX" "$JOB_DIR/progress.jsonl" <<'PY'
from __future__ import annotations
import gzip, json, os, sys
from datetime import datetime, timezone
date, index, total, observed_path, filtered_observed_path, fingerprint_report_path, summary_path, new_trace_index, trace_index, route_index, progress_path = sys.argv[1:12]
with gzip.open(observed_path, "rt", encoding="utf-8") as handle:
    observed = json.load(handle)
with gzip.open(filtered_observed_path, "rt", encoding="utf-8") as handle:
    filtered_observed = json.load(handle)
fingerprints = json.loads(open(fingerprint_report_path, encoding="utf-8").read()) if os.path.exists(fingerprint_report_path) else {}
summary = json.loads(open(summary_path, encoding="utf-8").read())
new_trace_count = sum(1 for line in open(new_trace_index, encoding="utf-8")) if os.path.exists(new_trace_index) else 0
seen_trace_count = sum(1 for line in open(trace_index, encoding="utf-8")) if os.path.exists(trace_index) else 0
seen_route_count = sum(1 for line in open(route_index, encoding="utf-8")) if os.path.exists(route_index) else 0
row = {
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "date": date,
    "dayIndex": int(index),
    "days": int(total),
    "observedRoutes": len(observed.get("routes", [])),
    "dedupObservedRoutes": len(filtered_observed.get("routes", [])),
    "routeFingerprintFilter": fingerprints,
    "observedBytes": os.path.getsize(observed_path),
    "newTraceHashes": new_trace_count,
    "seenTraceHashes": seen_trace_count,
    "seenRouteFingerprints": seen_route_count,
    "validation": summary.get("summary"),
}
with open(progress_path, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
print(json.dumps(row, ensure_ascii=False))
PY

    write_status "running" "cleanup-raw-downloads" "$release_date" "$index"
    "$PYTHON_BIN" - "$release_download_dir" "$release_date" "$JOB_DIR/raw-cleanup-progress.jsonl" <<'PY'
from __future__ import annotations
import json, sys
from datetime import datetime, timezone
from pathlib import Path

release_dir = Path(sys.argv[1])
date = sys.argv[2]
progress_path = Path(sys.argv[3])
deleted = []
bytes_deleted = 0
patterns = ("*.tar.*", ".*.chunk", ".*.headers")
if release_dir.exists() and release_dir.name == date:
    for pattern in patterns:
        for path in sorted(release_dir.glob(pattern)):
            if not path.is_file():
                continue
            size = path.stat().st_size
            path.unlink()
            deleted.append(str(path))
            bytes_deleted += size
row = {
    "updatedAt": datetime.now(timezone.utc).isoformat(),
    "date": date,
    "releaseDir": str(release_dir),
    "deletedFiles": len(deleted),
    "deletedBytes": bytes_deleted,
}
with progress_path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
print(json.dumps(row, ensure_ascii=False))
PY
    echo "=== [$index/$day_count] completed $release_date $(date -u +%FT%TZ) ==="
  done

  if [[ -n "$prefetch_pid" ]]; then
    write_status "running" "wait-final-prefetch" "$prefetch_date" "$day_count"
    echo "=== waiting for final prefetched raw $prefetch_date pid=$prefetch_pid $(date -u +%FT%TZ) ==="
    wait "$prefetch_pid"
  fi

  write_status "complete" "complete" "" "$day_count"
  cp "$STATUS" "$JOB_DIR/done.json"
  echo "=== daily observed ADS-B IFR pipeline completed $(date -u +%FT%TZ) ==="
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  printf '{"state":"already_running","pid":%s,"jobDir":"%s","log":"%s","outputDir":"%s","status":"%s"}\n' "$(cat "$PID_FILE")" "$JOB_DIR" "$LOG" "$OUTPUT_DIR" "$STATUS"
  exit 0
fi

write_status "starting" "launch"
if command -v launchctl >/dev/null 2>&1; then
  launchctl remove "$LABEL" 2>/dev/null || true
  launchctl submit -l "$LABEL" -- /bin/bash "$ROOT/AviationDB/scripts/run_observed_routes_daily_ifr_21d.sh" __worker
  printf '{"state":"started","launcher":"launchctl","label":"%s","jobDir":"%s","log":"%s","outputDir":"%s","status":"%s"}\n' "$LABEL" "$JOB_DIR" "$LOG" "$OUTPUT_DIR" "$STATUS"
else
  nohup /bin/bash "$ROOT/AviationDB/scripts/run_observed_routes_daily_ifr_21d.sh" __worker > "$LOG" 2>&1 &
  pid=$!
  printf '%s\n' "$pid" > "$PID_FILE"
  printf '{"state":"started","launcher":"nohup","pid":%s,"jobDir":"%s","log":"%s","outputDir":"%s","status":"%s"}\n' "$pid" "$JOB_DIR" "$LOG" "$OUTPUT_DIR" "$STATUS"
fi

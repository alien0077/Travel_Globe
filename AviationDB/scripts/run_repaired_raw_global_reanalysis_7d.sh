#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VERSION="${TRAVEL_GLOBE_REANALYSIS_VERSION:-v4}"
JOB_DIR="/private/tmp/travel-globe-repaired-raw-global-reanalysis-7d-${VERSION}"
STATUS="$JOB_DIR/status.json"
DONE="$JOB_DIR/done.json"
LOG="$JOB_DIR/pipeline.log"
LOCK_DIR="$JOB_DIR/worker.lock"
PID_FILE="$JOB_DIR/pid"
LABEL="travel-globe-repaired-raw-global-reanalysis-7d-${VERSION}"
PYTHON_BIN="${PYTHON_BIN:-/usr/local/bin/python3}"
RAW_ROOT="$ROOT/AviationDB/data/raw/adsblol"
RAW_DIR="$RAW_ROOT/2026-08-01"
RAW_RELEASE_URL="https://github.com/adsblol/globe_history_2026/releases/download/v2026.08.01-planes-readsb-prod-0"
REPAIR_MANIFEST="$RAW_DIR/raw-repair-2026-08-01.json"

RAW_DERIVED="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/corridor-7d-v2-repaired-2026-08-01-${VERSION}"
CROSS_RAW="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-cross-continent-7d-025-repaired-2026-08-01-${VERSION}"
CROSS_NETWORK="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-corridor-network-7d-025-repaired-2026-08-01-${VERSION}"
GLOBAL_ROOT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025-repaired-2026-08-01-${VERSION}"
BASE_DERIVED="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/corridor-7d-v2"
INPUT_DERIVED="${TRAVEL_GLOBE_REANALYSIS_INPUT_DERIVED:-$RAW_DERIVED}"
SKIP_RAW_OBSERVATION="${TRAVEL_GLOBE_REANALYSIS_SKIP_RAW_OBSERVATION:-false}"
RESUME_FROM_ASSEMBLE="${TRAVEL_GLOBE_REANALYSIS_RESUME_FROM_ASSEMBLE:-false}"
BASE_GRAPH="${TRAVEL_GLOBE_REANALYSIS_BASE_GRAPH:-$RAW_DERIVED/global/global-corridor-graph.json.gz}"
# The relay graph is produced by the canonical relay assembler.  It is not
# inside each repaired daily-derived version, so never infer this path from
# RAW_DERIVED.  A missing relay input must fail during preflight, before any
# expensive downstream work starts.
BASE_RELAY="${TRAVEL_GLOBE_REANALYSIS_BASE_RELAY:-$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/corridor-7d-v2/global/relay-network/global-corridor-relay-network.json.gz}"
CROSS_NETWORK_INPUT="${TRAVEL_GLOBE_REANALYSIS_CROSS_NETWORK_INPUT:-$CROSS_NETWORK/global-corridor-network.json.gz}"
TRACE_CONTINUITY_SOURCE_ROOT="${TRAVEL_GLOBE_REANALYSIS_TRACE_CONTINUITY_SOURCE_ROOT:-}"
TRACE_CONTINUITY_BASE_NETWORK="${TRAVEL_GLOBE_REANALYSIS_TRACE_CONTINUITY_BASE_NETWORK:-}"
TRACE_CONTINUITY_REVIEW="${TRAVEL_GLOBE_REANALYSIS_TRACE_CONTINUITY_REVIEW:-$JOB_DIR/trace-continuity-review.json}"
REUSE_RESOLUTION_INPUT="${TRAVEL_GLOBE_REANALYSIS_REUSE_RESOLUTION_INPUT:-}"
FAILED="$JOB_DIR/failed.json"

mkdir -p "$JOB_DIR" "$RAW_DERIVED" "$CROSS_RAW" "$CROSS_NETWORK" "$GLOBAL_ROOT"

if [[ "${1:-}" == "status" ]]; then
  cat "$STATUS" 2>/dev/null || printf '{"state":"not_started","jobDir":"%s"}\n' "$JOB_DIR"
  exit 0
fi
if [[ "${1:-}" != "__worker" ]] && [[ -s "$DONE" ]] && rg -q '"state": "complete"' "$DONE"; then
  printf '{"state":"already_complete","done":"%s"}\n' "$DONE"
  exit 0
fi
if [[ "${1:-}" != "__worker" ]] && [[ -s "$FAILED" ]]; then
  printf '{"state":"blocked_after_failure","failed":"%s"}\n' "$FAILED"
  exit 2
fi

if [[ "${1:-}" == "__worker" ]]; then
  if [[ -s "$DONE" ]] && rg -q '"state": "complete"' "$DONE"; then exit 0; fi
  if [[ -s "$FAILED" ]]; then exit 2; fi
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then exit 0; fi
  echo "$$" > "$PID_FILE"
  on_exit() {
    local rc=$?
    rm -f "$PID_FILE"
    rmdir "$LOCK_DIR" 2>/dev/null || true
    if [[ "$rc" -ne 0 ]]; then
      "$PYTHON_BIN" - "$FAILED" "$rc" "$JOB_DIR" "$LOG" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
path,rc,job_dir,log=sys.argv[1:]
payload={"state":"failed","exitCode":int(rc),"updatedAt":datetime.now(timezone.utc).isoformat(),"jobDir":job_dir,"log":log}
tmp=Path(path).with_suffix(Path(path).suffix+".part")
tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
tmp.replace(path)
PY
      launchctl remove "$LABEL" 2>/dev/null || true
    fi
    return "$rc"
  }
  trap on_exit EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"

  write_status() {
    "$PYTHON_BIN" - "$STATUS" "$1" "$2" "$JOB_DIR" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
path,state,phase,job_dir=sys.argv[1:]
Path(path).write_text(json.dumps({"state":state,"phase":phase,"updatedAt":datetime.now(timezone.utc).isoformat(),"jobDir":job_dir,"log":str(Path(job_dir)/"pipeline.log")},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
PY
  }
  run_step() {
    local name="$1"; shift
    write_status running "$name"
    echo "=== $name started $(date -u +%FT%TZ) ==="
    "$@"
    echo "=== $name completed $(date -u +%FT%TZ) ==="
  }

  write_status running preflight
  if [[ "$RESUME_FROM_ASSEMBLE" == "true" ]]; then
    for required in "$BASE_GRAPH" "$BASE_RELAY"; do
      if [[ ! -s "$required" ]]; then
        echo "missing assemble input: $required"
        exit 20
      fi
    done
    if [[ -n "$TRACE_CONTINUITY_SOURCE_ROOT" ]]; then
      if [[ -z "$TRACE_CONTINUITY_BASE_NETWORK" ]]; then
        TRACE_CONTINUITY_BASE_NETWORK="$TRACE_CONTINUITY_SOURCE_ROOT/global-corridor-network.json.gz"
      fi
      if [[ ! -s "$TRACE_CONTINUITY_BASE_NETWORK" ]]; then
        echo "missing trace continuity base network: $TRACE_CONTINUITY_BASE_NETWORK"
        exit 20
      fi
      for daily in "$TRACE_CONTINUITY_SOURCE_ROOT"/2026-*.json.gz; do
        [[ -s "$daily" ]] || { echo "missing trace continuity daily input: $daily"; exit 20; }
      done
    elif [[ ! -s "$CROSS_NETWORK_INPUT" ]]; then
      echo "missing assemble input: $CROSS_NETWORK_INPUT"
      exit 20
    fi
    if [[ -n "$REUSE_RESOLUTION_INPUT" && ! -s "$REUSE_RESOLUTION_INPUT" ]]; then
      echo "missing reusable resolution evidence: $REUSE_RESOLUTION_INPUT"
      exit 20
    fi
    echo "resume_from_assemble=true"
    echo "base_graph=$BASE_GRAPH"
    echo "base_relay=$BASE_RELAY"
    echo "cross_network=$CROSS_NETWORK_INPUT"
    echo "trace_continuity_source=$TRACE_CONTINUITY_SOURCE_ROOT"
    echo "reuse_resolution_input=$REUSE_RESOLUTION_INPUT"
  fi
  if [[ "$RESUME_FROM_ASSEMBLE" != "true" ]]; then
    if [[ ! -s "$REPAIR_MANIFEST" ]]; then
      run_step raw_repair "$PYTHON_BIN" AviationDB/scripts/replace_adsblol_release_set.py \
        --date 2026-08-01 --raw-dir "$RAW_DIR" \
        --old-prefix v2026.08.01-planes-readsb-staging-0 \
        --new-prefix v2026.08.01-planes-readsb-prod-0 \
        --release-url "$RAW_RELEASE_URL" --status "$JOB_DIR/raw-repair.status.json"
    else
      echo "raw repair manifest already exists: $REPAIR_MANIFEST"
    fi
    if [[ "$SKIP_RAW_OBSERVATION" == "true" ]]; then
      echo "raw_observation reused from input root: $INPUT_DERIVED"
    else
      run_step raw_observation "$PYTHON_BIN" AviationDB/scripts/prepare_repaired_raw_observation_7d.py \
        --raw-root "$RAW_ROOT" --base-output-root "$BASE_DERIVED" --output-root "$RAW_DERIVED" \
        --repair-date 2026-08-01 --job-dir "$JOB_DIR/raw"
      INPUT_DERIVED="$RAW_DERIVED"
    fi
    run_step merge "$PYTHON_BIN" AviationDB/scripts/merge_corridor_7d.py \
      --job-dir "$JOB_DIR/merge" --input-root "$INPUT_DERIVED" --output-root "$RAW_DERIVED/global"
    BASE_GRAPH="$RAW_DERIVED/global/global-corridor-graph.json.gz"
    run_step chains "$PYTHON_BIN" AviationDB/scripts/build_global_corridor_chains.py \
      --db "$JOB_DIR/merge/corridor-merge.sqlite" --output "$RAW_DERIVED/global/global-corridor-chains.json.gz"
    run_step bridges "$PYTHON_BIN" AviationDB/scripts/build_global_corridor_bridges.py \
      --db "$JOB_DIR/merge/corridor-merge.sqlite" --chains "$RAW_DERIVED/global/global-corridor-chains.json.gz" \
      --output "$RAW_DERIVED/global/global-corridor-bridges.json.gz" --status "$JOB_DIR/bridge-status.json"
    run_step evidence_index "$PYTHON_BIN" AviationDB/scripts/build_global_corridor_evidence_index.py \
      --db "$JOB_DIR/merge/corridor-merge.sqlite" --chains "$RAW_DERIVED/global/global-corridor-chains.json.gz" \
      --bridges "$RAW_DERIVED/global/global-corridor-bridges.json.gz" --output "$RAW_DERIVED/global/evidence-index.json.gz" \
      --review-output "$RAW_DERIVED/global/global-corridor-bridge-review.json"
    run_step cross_stage_025 "$PYTHON_BIN" AviationDB/scripts/prepare_repaired_cross_continent_7d.py \
      --base-root "$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-cross-continent-7d-025" \
      --output-root "$CROSS_RAW" --repair-date 2026-08-01 --status "$JOB_DIR/cross-stage-status.json"
    run_step cross_continent_025 "$PYTHON_BIN" AviationDB/scripts/extract_global_cross_continent_corridors_7d.py \
      --raw-root "$RAW_ROOT" --output-root "$CROSS_RAW" --status "$JOB_DIR/cross-raw-status.json" --cell-deg 0.25 --include-asia-northamerica
    run_step cross_integrate "$PYTHON_BIN" AviationDB/scripts/integrate_global_cross_continent_corridors_7d.py \
      --cross-all-input "$CROSS_RAW/global-cross-continent-corridors.json.gz" --output-root "$CROSS_NETWORK" \
      --status "$JOB_DIR/cross-integrate-status.json"
  else
    echo "assemble inputs preflight complete; skipping completed upstream phases"
  fi
  if [[ -n "$TRACE_CONTINUITY_SOURCE_ROOT" && ! -s "$CROSS_NETWORK_INPUT" ]]; then
    if [[ -z "$TRACE_CONTINUITY_BASE_NETWORK" ]]; then
      TRACE_CONTINUITY_BASE_NETWORK="$TRACE_CONTINUITY_SOURCE_ROOT/global-corridor-network.json.gz"
    fi
    run_step trace_continuity_relay "$PYTHON_BIN" AviationDB/scripts/stitch_trace_continuity_7d.py \
      --cross-root "$TRACE_CONTINUITY_SOURCE_ROOT" --input-network "$TRACE_CONTINUITY_BASE_NETWORK" \
      --output "$CROSS_NETWORK_INPUT" --review-output "$TRACE_CONTINUITY_REVIEW" \
      --status "$JOB_DIR/trace-continuity-status.json"
  else
    echo "trace_continuity_relay output already exists; reusing: $CROSS_NETWORK_INPUT"
  fi
  run_step assemble "$PYTHON_BIN" AviationDB/scripts/assemble_global_corridor_network_7d.py \
    --base-graph "$BASE_GRAPH" \
    --base-relay "$BASE_RELAY" \
    --cross-network "$CROSS_NETWORK_INPUT" --output-root "$GLOBAL_ROOT" \
    --status "$JOB_DIR/assemble-status.json"
  run_step khh_validation "$PYTHON_BIN" AviationDB/scripts/validate_khh_global_network_7d.py \
    --network "$GLOBAL_ROOT/global-corridor-network.json.gz" --airports "$ROOT/shared/offline-packs/core-global/airports-index.json" \
    --output "$GLOBAL_ROOT/khh-validation.json"
  run_step connectivity_audit "$PYTHON_BIN" AviationDB/scripts/audit_global_network_connectivity_7d.py \
    --network "$GLOBAL_ROOT/global-corridor-network.json.gz" --airports "$ROOT/shared/offline-packs/core-global/airports-index.json" \
    --output-root "$GLOBAL_ROOT/connectivity" --status "$JOB_DIR/audit-status.json"
  run_step finalize_layers "$PYTHON_BIN" AviationDB/scripts/finalize_global_corridor_layers_7d.py \
    --network "$GLOBAL_ROOT/global-corridor-network.json.gz" --audit "$GLOBAL_ROOT/connectivity/global-connectivity-audit.json.gz" \
    --raw-validation "$GLOBAL_ROOT/khh-validation.json" --output-root "$GLOBAL_ROOT/connectivity" --status "$JOB_DIR/finalize-status.json"
  if [[ -n "$REUSE_RESOLUTION_INPUT" ]]; then
    run_step resolution_overlay_reuse "$PYTHON_BIN" AviationDB/scripts/reuse_resolution_overlay_7d.py \
      --network "$GLOBAL_ROOT/global-corridor-network.json.gz" --prior-overlay "$REUSE_RESOLUTION_INPUT" \
      --output-root "$GLOBAL_ROOT/resolution" --status "$JOB_DIR/resolution-status.json"
  else
    run_step resolution_overlay "$PYTHON_BIN" AviationDB/scripts/resolve_global_gap_and_khh_endpoints_7d.py \
      --network "$GLOBAL_ROOT/global-corridor-network.json.gz" --airport-index "$ROOT/shared/offline-packs/core-global/airports-index.json" \
      --raw-root "$RAW_ROOT" --output-root "$GLOBAL_ROOT/resolution" --status "$JOB_DIR/resolution-status.json"
  fi
  run_step reference_validation "$PYTHON_BIN" AviationDB/scripts/validate_reference_corridor_pairs_7d.py \
    --network "$GLOBAL_ROOT/global-corridor-network.json.gz" \
    --audit "$GLOBAL_ROOT/connectivity/global-connectivity-audit.json.gz" \
    --airports "$ROOT/shared/offline-packs/core-global/airports-index.json" \
    --output "$GLOBAL_ROOT/reference-corridor-pairs-validation.json"
  "$PYTHON_BIN" - "$STATUS" "$DONE" "$JOB_DIR" "$LOG" "$GLOBAL_ROOT" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
status,done,job_dir,log,output_root=sys.argv[1:]
payload={"state":"complete","phase":"all_steps_complete","updatedAt":datetime.now(timezone.utc).isoformat(),"jobDir":job_dir,"log":log,"outputRoot":output_root}
Path(status).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
Path(done).write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
PY
  launchctl remove "$LABEL" 2>/dev/null || true
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  printf '{"state":"already_running","pid":%s,"jobDir":"%s","log":"%s"}\n' "$(cat "$PID_FILE")" "$JOB_DIR" "$LOG"
  exit 0
fi
python3 - "$STATUS" "$JOB_DIR" "$LOG" <<'PY'
import json,sys
from datetime import datetime,timezone
from pathlib import Path
status,job_dir,log=sys.argv[1:]
Path(status).write_text(json.dumps({"state":"starting","updatedAt":datetime.now(timezone.utc).isoformat(),"jobDir":job_dir,"log":log},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
PY
launchctl remove "$LABEL" 2>/dev/null || true
  launchctl submit -l "$LABEL" -- /usr/bin/env \
  "TRAVEL_GLOBE_REANALYSIS_VERSION=$VERSION" \
  "TRAVEL_GLOBE_REANALYSIS_INPUT_DERIVED=$INPUT_DERIVED" \
  "TRAVEL_GLOBE_REANALYSIS_SKIP_RAW_OBSERVATION=$SKIP_RAW_OBSERVATION" \
  "TRAVEL_GLOBE_REANALYSIS_RESUME_FROM_ASSEMBLE=$RESUME_FROM_ASSEMBLE" \
  "TRAVEL_GLOBE_REANALYSIS_BASE_GRAPH=$BASE_GRAPH" \
  "TRAVEL_GLOBE_REANALYSIS_BASE_RELAY=$BASE_RELAY" \
  "TRAVEL_GLOBE_REANALYSIS_CROSS_NETWORK_INPUT=$CROSS_NETWORK_INPUT" \
  "TRAVEL_GLOBE_REANALYSIS_TRACE_CONTINUITY_SOURCE_ROOT=$TRACE_CONTINUITY_SOURCE_ROOT" \
  "TRAVEL_GLOBE_REANALYSIS_TRACE_CONTINUITY_BASE_NETWORK=$TRACE_CONTINUITY_BASE_NETWORK" \
  "TRAVEL_GLOBE_REANALYSIS_TRACE_CONTINUITY_REVIEW=$TRACE_CONTINUITY_REVIEW" \
  "TRAVEL_GLOBE_REANALYSIS_REUSE_RESOLUTION_INPUT=$REUSE_RESOLUTION_INPUT" \
  /bin/bash "$ROOT/AviationDB/scripts/run_repaired_raw_global_reanalysis_7d.sh" __worker
printf '{"state":"started","launcher":"launchctl","label":"%s","jobDir":"%s","log":"%s","status":"%s"}\n' "$LABEL" "$JOB_DIR" "$LOG" "$STATUS"

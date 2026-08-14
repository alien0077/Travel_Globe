#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB="/private/tmp/travel-globe-waypoint-chain-reanalysis-7d-v14"
STATUS="$JOB/status.json"
DONE="$JOB/done.json"
FAILED="$JOB/failed.json"
LOG="$JOB/pipeline.log"
LABEL="travel-globe-waypoint-chain-reanalysis-7d-v14"
PYTHON="/usr/local/bin/python3"
STRICT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025-repaired-2026-08-01-v13"
SOURCE="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025-repaired-2026-08-01-v11"
OUT="$ROOT/AviationDB/data/releases/private/observed-routes/adsblol/global-network-7d-025-repaired-2026-08-01-v14"

if [[ "${1:-}" == "status" ]]; then
  cat "$STATUS" 2>/dev/null || printf '{"state":"not_started"}\n'
  exit 0
fi

if [[ "${1:-}" == "__worker" ]]; then
  mkdir -p "$JOB" "$OUT"
  [[ ! -s "$DONE" ]] || exit 0
  [[ ! -s "$FAILED" ]] || exit 2
  mkdir "$JOB/lock" 2>/dev/null || exit 0
  echo $$ > "$JOB/pid"
  cleanup() { rm -f "$JOB/pid"; rmdir "$JOB/lock" 2>/dev/null || true; }
  on_exit() {
    rc=$?
    if [[ "$rc" -ne 0 && ! -s "$FAILED" && ! -s "$DONE" ]]; then
      "$PYTHON" -c 'import json,sys; from datetime import datetime,timezone; from pathlib import Path; f,s,j,l,r=sys.argv[1:]; p={"state":"failed","exitCode":int(r),"updatedAt":datetime.now(timezone.utc).isoformat(),"jobDir":j,"log":l}; [Path(x).with_suffix(Path(x).suffix+".part").write_text(json.dumps(p,ensure_ascii=False,indent=2)+"\n",encoding="utf-8") for x in (f,s)]; [Path(x).with_suffix(Path(x).suffix+".part").replace(x) for x in (f,s)]' "$FAILED" "$STATUS" "$JOB" "$LOG" "$rc"
    fi
    cleanup
    launchctl remove "$LABEL" 2>/dev/null || true
    return "$rc"
  }
  trap on_exit EXIT
  exec >> "$LOG" 2>&1
  cd "$ROOT"
  status() { "$PYTHON" -c 'import json,sys; from datetime import datetime,timezone; from pathlib import Path; p=Path(sys.argv[1]); x={"state":"running","phase":sys.argv[2],"updatedAt":datetime.now(timezone.utc).isoformat(),"jobDir":sys.argv[3],"outputRoot":sys.argv[4],"rawRescan":False}; t=p.with_suffix(p.suffix+".part"); t.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); t.replace(p)' "$STATUS" "$1" "$JOB" "$OUT"; }
  status waypoint_chain
  "$PYTHON" AviationDB/scripts/build_inferred_waypoint_chain_network_7d.py --strict-network "$STRICT/global-corridor-network.json.gz" --relay-source-network "$SOURCE/global-corridor-network.json.gz" --output-network "$OUT/global-corridor-network.json.gz" --review-output "$OUT/waypoint-chain-review.json"
  status khh_validation
  "$PYTHON" AviationDB/scripts/validate_khh_global_network_7d.py --network "$OUT/global-corridor-network.json.gz" --airports "$ROOT/shared/offline-packs/core-global/airports-index.json" --output "$OUT/khh-validation.json"
  status connectivity_audit
  "$PYTHON" AviationDB/scripts/audit_global_network_connectivity_7d.py --network "$OUT/global-corridor-network.json.gz" --airports "$ROOT/shared/offline-packs/core-global/airports-index.json" --output-root "$OUT/connectivity" --status "$JOB/audit.status.json"
  status finalize
  "$PYTHON" AviationDB/scripts/finalize_global_corridor_layers_7d.py --network "$OUT/global-corridor-network.json.gz" --audit "$OUT/connectivity/global-connectivity-audit.json.gz" --raw-validation "$OUT/khh-validation.json" --output-root "$OUT/connectivity" --status "$JOB/finalize.status.json"
  status reference_qa
  set +e
  "$PYTHON" AviationDB/scripts/validate_reference_corridor_pairs_7d.py --network "$OUT/global-corridor-network.json.gz" --audit "$OUT/connectivity/global-connectivity-audit.json.gz" --airports "$ROOT/shared/offline-packs/core-global/airports-index.json" --output "$OUT/reference-corridor-pairs-validation.json"
  rc=$?
  set -e
  [[ "$rc" -eq 0 || "$rc" -eq 2 ]]
  status route_shape_qa
  set +e
  "$PYTHON" AviationDB/scripts/validate_reference_route_shapes_7d.py --network "$OUT/global-corridor-network.json.gz" --audit "$OUT/connectivity/global-connectivity-audit.json.gz" --output "$OUT/reference-route-shape-qa.json"
  rc=$?
  set -e
  [[ "$rc" -eq 0 || "$rc" -eq 2 ]]
  "$PYTHON" -c 'import json,sys; from datetime import datetime,timezone; from pathlib import Path; s,d,j,l,o=sys.argv[1:]; p={"state":"complete","phase":"all_steps_complete","updatedAt":datetime.now(timezone.utc).isoformat(),"jobDir":j,"log":l,"outputRoot":o,"rawRescan":False}; [Path(x).with_suffix(Path(x).suffix+".part").write_text(json.dumps(p,ensure_ascii=False,indent=2)+"\n",encoding="utf-8") for x in (s,d)]; [Path(x).with_suffix(Path(x).suffix+".part").replace(x) for x in (s,d)]' "$STATUS" "$DONE" "$JOB" "$LOG" "$OUT"
  trap - EXIT
  cleanup
  launchctl remove "$LABEL" 2>/dev/null || true
  exit 0
fi

mkdir -p "$JOB"
[[ ! -s "$DONE" ]] || { cat "$DONE"; exit 0; }
[[ ! -s "$FAILED" ]] || { cat "$FAILED"; exit 2; }
launchctl remove "$LABEL" 2>/dev/null || true
launchctl submit -l "$LABEL" -- /bin/bash "$ROOT/AviationDB/scripts/run_waypoint_chain_reanalysis_7d_v14.sh" __worker
printf '{"state":"started","label":"%s","jobDir":"%s","status":"%s"}\n' "$LABEL" "$JOB" "$STATUS"

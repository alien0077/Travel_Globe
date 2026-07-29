#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
JOB_DIR="/private/tmp/travel-globe-route-source-fusion"
LOG="$JOB_DIR/route-source-fusion.log"
STATUS="$JOB_DIR/status.json"
PID_FILE="$JOB_DIR/pid"

mkdir -p "$JOB_DIR"

if [[ "${1:-}" == "__worker" ]]; then
  printf '{"state":"running","startedAt":"%s","jobDir":"%s","log":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" > "$STATUS"
  cd "$ROOT"
  if python3 AviationDB/scripts/build_route_source_fusion.py; then
    printf '{"state":"complete","completedAt":"%s","jobDir":"%s","log":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" > "$STATUS"
  else
    rc=$?
    printf '{"state":"failed","failedAt":"%s","exitCode":%s,"jobDir":"%s","log":"%s"}\n' "$(date -u +%FT%TZ)" "$rc" "$JOB_DIR" "$LOG" > "$STATUS"
    exit "$rc"
  fi
  exit 0
fi

if [[ "${1:-}" == "status" ]]; then
  if [[ -f "$STATUS" ]]; then
    cat "$STATUS"
  else
    printf '{"state":"not_started","jobDir":"%s"}\n' "$JOB_DIR"
  fi
  exit 0
fi

if [[ "${1:-}" == "stop" ]]; then
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")"
    printf '{"state":"stop_requested","pid":%s,"jobDir":"%s"}\n' "$(cat "$PID_FILE")" "$JOB_DIR" > "$STATUS"
  fi
  cat "$STATUS"
  exit 0
fi

if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  printf '{"state":"already_running","pid":%s,"jobDir":"%s","log":"%s"}\n' "$(cat "$PID_FILE")" "$JOB_DIR" "$LOG"
  exit 0
fi

printf '{"state":"starting","startedAt":"%s","jobDir":"%s","log":"%s"}\n' "$(date -u +%FT%TZ)" "$JOB_DIR" "$LOG" > "$STATUS"
nohup /bin/bash "$ROOT/AviationDB/scripts/run_route_source_fusion_until_done.sh" __worker > "$LOG" 2>&1 &

pid=$!
printf '%s\n' "$pid" > "$PID_FILE"
printf '{"state":"started","pid":%s,"jobDir":"%s","log":"%s","status":"%s"}\n' "$pid" "$JOB_DIR" "$LOG" "$STATUS"

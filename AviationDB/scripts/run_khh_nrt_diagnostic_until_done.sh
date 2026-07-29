#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/../.."

LOG="AviationDB/logs/khh-nrt-diagnostic.log"
mkdir -p "$(dirname "$LOG")"

echo "" >> "$LOG"
echo "=== khh_nrt_diagnostic started $(date) ===" >> "$LOG"

PYTHONUNBUFFERED=1 python3 AviationDB/scripts/diagnose_observed_route_gap.py \
  --date 2026-07-21 \
  --origin KHH \
  --destination NRT >> "$LOG" 2>&1
status=$?

echo "=== khh_nrt_diagnostic exited status=${status} $(date) ===" >> "$LOG"
exit "$status"

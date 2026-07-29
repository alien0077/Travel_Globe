#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/../.."

LOG="AviationDB/logs/khh-corridor-scan-20260722.log"
mkdir -p "$(dirname "$LOG")"

echo "" >> "$LOG"
echo "=== khh_corridor_scan_20260722 started $(date) ===" >> "$LOG"

PYTHONUNBUFFERED=1 python3 AviationDB/scripts/scan_observed_route_corridor.py \
  --date 2026-07-22 \
  --routes DMK-KHH KHH-NRT >> "$LOG" 2>&1
status=$?

echo "=== khh_corridor_scan_20260722 exited status=${status} $(date) ===" >> "$LOG"
exit "$status"

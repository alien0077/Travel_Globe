#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/../.."

LOG="AviationDB/logs/khh-endpoint-recovery-scan-20260722.log"
mkdir -p "$(dirname "$LOG")"

echo "" >> "$LOG"
echo "=== khh_endpoint_recovery_scan_20260722 started $(date) ===" >> "$LOG"

PYTHONUNBUFFERED=1 python3 AviationDB/scripts/scan_khh_endpoint_recovery.py \
  --date 2026-07-22 \
  --airport KHH >> "$LOG" 2>&1
status=$?

echo "=== khh_endpoint_recovery_scan_20260722 exited status=${status} $(date) ===" >> "$LOG"
exit "$status"

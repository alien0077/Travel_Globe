#!/usr/bin/env bash
set -u

cd "$(dirname "$0")/../.."

LOG="AviationDB/logs/observed-routes-21d.log"
mkdir -p "$(dirname "$LOG")"

echo "" >> "$LOG"
echo "=== observed_routes_21d supervisor started $(date) ===" >> "$LOG"

attempt=1
while true; do
  echo "=== attempt ${attempt} started $(date) ===" >> "$LOG"
  PYTHONUNBUFFERED=1 python3 AviationDB/scripts/build_observed_routes_range.py \
    --year 2026 \
    --start-date 2026-07-05 \
    --days 14 \
    --seed-pack AviationDB/data/releases/private/observed-routes/adsblol/observed-routes.global.json.gz \
    --cleanup-downloads >> "$LOG" 2>&1
  status=$?
  echo "=== attempt ${attempt} exited status=${status} $(date) ===" >> "$LOG"
  if [[ "$status" -eq 0 ]]; then
    echo "=== observed_routes_21d supervisor completed $(date) ===" >> "$LOG"
    exit 0
  fi
  attempt=$((attempt + 1))
  sleep 120
done

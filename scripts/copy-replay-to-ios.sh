#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SOURCE_DIR="$ROOT_DIR/replay-engine/dist"
TARGET_DIR="$ROOT_DIR/ios/TravelGlobe/Resources/ReplayEngine"

if [[ ! -f "$SOURCE_DIR/index.html" ]]; then
  echo "Replay Engine build not found. Run scripts/build-replay-engine.sh first." >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"
ditto "$SOURCE_DIR" "$TARGET_DIR"
LC_ALL=C perl -0pi -e 's#\./assets/index\.js#./index.js#g; s#\./assets/index\.css#./index.css#g' "$TARGET_DIR/index.html"
echo "Copied Replay Engine build to $TARGET_DIR"

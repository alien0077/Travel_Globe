#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-4174}"

npm --prefix replay-engine run build
echo "Serving Travel Globe static build at http://127.0.0.1:$PORT/"
python3 -m http.server "$PORT" --directory replay-engine/dist

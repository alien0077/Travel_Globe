#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

PYTHON_BIN="${PYTHON_BIN:-python3.12}"
cd "$ROOT_DIR/AviationDB"
PYTHONPATH=src "$PYTHON_BIN" -m aviationdb build-all

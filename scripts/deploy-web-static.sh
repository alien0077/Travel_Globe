#!/usr/bin/env bash
set -euo pipefail

npm --prefix replay-engine run typecheck
npm --prefix replay-engine run test
npm --prefix replay-engine run build

echo "Static build ready: replay-engine/dist"
echo "GitHub Pages deployment is configured in .github/workflows/web-static.yml."
echo "Push this repository to GitHub and run the Web Static Hosting workflow, or serve locally with scripts/serve-web-static.sh."

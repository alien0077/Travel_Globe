#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-web}"
SCHEME="TravelGlobe"
BUNDLE_ID="com.alienchang.TravelGlobe"
DEVICE_KEYWORD="${DEVICE_KEYWORD:-iPhone}"
XCODE_PATH="${XCODE_PATH:-/Applications/Xcode.app/Contents/Developer}"
XCODEGEN="${XCODEGEN:-/Users/alien/Desktop/xcodegen/bin/xcodegen}"
REMOTE="${REMOTE:-origin}"
BRANCH="${BRANCH:-main}"
WEB_URL="${WEB_URL:-https://alien0077.github.io/Travel_Globe}"

usage() {
  cat <<'EOF'
Usage:
  ./deploy.sh [web|ios-device]

Modes:
  web         Verify, push main, watch GitHub Pages workflow, and check live URLs.
  ios-device Build, install, and launch the iOS app on a connected physical iPhone.

Environment:
  REMOTE=origin
  BRANCH=main
  WEB_URL=https://alien0077.github.io/Travel_Globe
  DEVICE_KEYWORD=iPhone
  XCODE_PATH=/Applications/Xcode.app/Contents/Developer
  XCODEGEN=/Users/alien/Desktop/xcodegen/bin/xcodegen
EOF
}

require_command() {
  local command_name="$1"
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "Missing required command: $command_name" >&2
    exit 1
  fi
}

resolve_device() {
  local udid=""
  local coredevice_id=""

  coredevice_id=$(DEVELOPER_DIR="$XCODE_PATH" xcrun devicectl list devices \
    | grep "$DEVICE_KEYWORD" \
    | grep -v "unavailable" \
    | grep "available" \
    | grep -oE "[0-9A-Fa-f-]{36}" || true)

  if [[ -n "$coredevice_id" ]]; then
    echo "devicectl:$coredevice_id"
    return
  fi

  udid=$(DEVELOPER_DIR="$XCODE_PATH" xcrun xctrace list devices \
    | awk '/^== Devices Offline ==/ {exit} /^== Devices ==/ {online=1; next} /^==/ {online=0} online {print}' \
    | grep "$DEVICE_KEYWORD" \
    | grep -oE "[0-9A-Fa-f]{8}-[0-9A-Fa-f]{16}|[0-9A-Fa-f-]{36}" || true)

  if [[ -n "$udid" ]]; then
    echo "ios-deploy:$udid"
  fi
}

verify_live_url() {
  local url="$1"
  local status=""
  status=$(curl -fsSIL -o /dev/null -w "%{http_code}" "$url")
  if [[ "$status" != "200" ]]; then
    echo "Live URL check failed: $url returned HTTP $status" >&2
    exit 1
  fi
  echo "✓ $url returned HTTP 200"
}

deploy_web() {
  require_command git
  require_command gh
  require_command npm
  require_command curl

  echo "[1/6] Running Replay Engine checks..."
  npm --prefix replay-engine run typecheck
  npm --prefix replay-engine run test
  npm --prefix replay-engine run build

  echo "[2/6] Checking repository state..."
  if [[ "$(git branch --show-current)" != "$BRANCH" ]]; then
    echo "Expected to deploy from branch '$BRANCH'; current branch is '$(git branch --show-current)'." >&2
    exit 1
  fi
  if [[ -n "$(git status --porcelain)" ]]; then
    echo "Working tree has uncommitted changes. Commit them before deploying." >&2
    git status --short
    exit 1
  fi

  echo "[3/6] Pushing $BRANCH to $REMOTE..."
  git push "$REMOTE" "$BRANCH"

  echo "[4/6] Triggering Web Static Hosting workflow..."
  local head_sha=""
  head_sha=$(git rev-parse HEAD)
  gh workflow run "Web Static Hosting" --repo alien0077/Travel_Globe --ref "$BRANCH"

  echo "Locating workflow run for $head_sha..."
  local run_id=""
  for attempt in {1..30}; do
    run_id=$(gh run list \
      --repo alien0077/Travel_Globe \
      --workflow "Web Static Hosting" \
      --branch "$BRANCH" \
      --limit 10 \
      --json databaseId,headSha \
      --jq "map(select(.headSha == \"$head_sha\")) | sort_by(.databaseId) | reverse | .[0].databaseId // empty")
    if [[ -n "$run_id" ]]; then
      break
    fi
    echo "Waiting for workflow run ($attempt/30)..."
    sleep 3
  done
  if [[ -z "$run_id" ]]; then
    echo "Unable to find the Web Static Hosting workflow run." >&2
    exit 1
  fi

  echo "[5/6] Watching Web Static Hosting workflow: $run_id"
  gh run watch "$run_id" --repo alien0077/Travel_Globe --exit-status

  echo "[6/6] Verifying live GitHub Pages assets..."
  verify_live_url "$WEB_URL/"
  verify_live_url "$WEB_URL/readme.html"
  verify_live_url "$WEB_URL/index.js"
  verify_live_url "$WEB_URL/index.css"
  echo "Travel Globe web deployment verified: $WEB_URL/"
}

deploy_ios_device() {
  require_command npm
  require_command xcrun
  require_command xcodebuild

  echo "[1/5] Building Replay Engine static bundle..."
  npm --prefix replay-engine run build

  echo "[2/5] Embedding Replay Engine in iOS resources..."
  scripts/copy-replay-to-ios.sh

  echo "[3/5] Generating Xcode project..."
  "$XCODEGEN" generate

  echo "[4/5] Building iOS app for a physical device..."
  DEVELOPER_DIR="$XCODE_PATH" \
  xcodebuild clean build \
    -scheme "$SCHEME" \
    -destination "generic/platform=iOS" \
    -allowProvisioningUpdates \
    -quiet \
    CODE_SIGN_STYLE=Automatic

  echo "[5/5] Locating connected device matching: $DEVICE_KEYWORD"
  local device_target=""
  for attempt in {1..15}; do
    device_target="$(resolve_device)"
    if [[ -n "$device_target" ]]; then
      break
    fi
    echo "Device not ready yet; retrying ($attempt/15)..."
    sleep 2
  done

  if [[ -z "$device_target" ]]; then
    echo "No connected device found. Connect and unlock an iPhone, tap Trust, then rerun this script." >&2
    exit 1
  fi

  local app_path=""
  app_path=$(DEVELOPER_DIR="$XCODE_PATH" xcodebuild -scheme "$SCHEME" -destination "generic/platform=iOS" -showBuildSettings | awk '/CODESIGNING_FOLDER_PATH/ {print $3; exit}')

  if [[ -z "$app_path" || ! -d "$app_path" ]]; then
    echo "Unable to locate built app bundle." >&2
    exit 1
  fi

  if [[ "$device_target" == ios-deploy:* ]]; then
    require_command ios-deploy
    local udid="${device_target#ios-deploy:}"
    echo "Installing $app_path on $udid with ios-deploy..."
    ios-deploy --id "$udid" --bundle "$app_path" --justlaunch
  else
    local coredevice_id="${device_target#devicectl:}"
    echo "Installing $app_path on $coredevice_id with devicectl..."
    DEVELOPER_DIR="$XCODE_PATH" xcrun devicectl device install app --device "$coredevice_id" "$app_path"
    DEVELOPER_DIR="$XCODE_PATH" xcrun devicectl device process launch --device "$coredevice_id" --terminate-existing "$BUNDLE_ID"
  fi
  echo "Travel Globe iOS app deployed and launched."
}

case "$MODE" in
  web)
    deploy_web
    ;;
  ios-device)
    deploy_ios_device
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 1
    ;;
esac

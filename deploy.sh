#!/usr/bin/env bash
set -euo pipefail

SCHEME="TravelGlobe"
BUNDLE_ID="com.alienchang.TravelGlobe"
DEVICE_KEYWORD="${DEVICE_KEYWORD:-iPhone}"
XCODE_PATH="${XCODE_PATH:-/Applications/Xcode.app/Contents/Developer}"
XCODEGEN="${XCODEGEN:-/Users/alien/Desktop/xcodegen/bin/xcodegen}"

resolve_device() {
  local udid=""
  local coredevice_id=""

  coredevice_id=$(DEVELOPER_DIR="$XCODE_PATH" xcrun devicectl list devices \
    | grep "$DEVICE_KEYWORD" \
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
DEVICE_TARGET=""
for attempt in {1..15}; do
  DEVICE_TARGET="$(resolve_device)"
  if [[ -n "$DEVICE_TARGET" ]]; then
    break
  fi
  echo "Device not ready yet; retrying ($attempt/15)..."
  sleep 2
done

if [[ -z "$DEVICE_TARGET" ]]; then
  echo "No connected device found. Connect and unlock an iPhone, tap Trust, then rerun this script." >&2
  exit 1
fi

APP_PATH=$(DEVELOPER_DIR="$XCODE_PATH" xcodebuild -scheme "$SCHEME" -destination "generic/platform=iOS" -showBuildSettings | awk '/CODESIGNING_FOLDER_PATH/ {print $3; exit}')

if [[ -z "$APP_PATH" || ! -d "$APP_PATH" ]]; then
  echo "Unable to locate built app bundle." >&2
  exit 1
fi

if [[ "$DEVICE_TARGET" == ios-deploy:* ]]; then
  UDID="${DEVICE_TARGET#ios-deploy:}"
  echo "Installing $APP_PATH on $UDID with ios-deploy..."
  ios-deploy --id "$UDID" --bundle "$APP_PATH" --justlaunch
else
  COREDEVICE_ID="${DEVICE_TARGET#devicectl:}"
  echo "Installing $APP_PATH on $COREDEVICE_ID with devicectl..."
  DEVELOPER_DIR="$XCODE_PATH" xcrun devicectl device install app --device "$COREDEVICE_ID" "$APP_PATH"
  DEVELOPER_DIR="$XCODE_PATH" xcrun devicectl device process launch --device "$COREDEVICE_ID" --terminate-existing "$BUNDLE_ID"
fi
echo "Travel Globe deployed and launched."

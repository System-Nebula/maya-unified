#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
EXTENSION_DIR="$ROOT/apps/maya-browser-extension"
TARGET="${MAYA_BROWSER_TARGET:-chromium-devtools}"
PROFILE="${MAYA_BROWSER_PROFILE:-$ROOT/.dev/maya-browser/chromium-profile}"
CDP_PORT="${MAYA_BROWSER_CDP_PORT:-9223}"
START_URL="${1:-${MAYA_BROWSER_START_URL:-about:blank}}"

if [[ "$TARGET" != "chromium" && "$TARGET" != "chromium-devtools" ]]; then
  echo "MAYA_BROWSER_TARGET must be chromium or chromium-devtools" >&2
  exit 2
fi

if [[ ! -d "$EXTENSION_DIR/node_modules" ]]; then
  npm --prefix "$EXTENSION_DIR" ci
fi
npm --prefix "$EXTENSION_DIR" run check
npm --prefix "$EXTENSION_DIR" run build

DIST="$EXTENSION_DIR/dist/$TARGET"
mkdir -p "$PROFILE"

echo "Maya Browser Companion remote-control profile"
echo "  extension: $TARGET"
echo "  profile:   $PROFILE"
echo "  CDP:       http://127.0.0.1:$CDP_PORT"
echo "  start URL: $START_URL"

exec chromium \
  --user-data-dir="$PROFILE" \
  --load-extension="$DIST" \
  --disable-extensions-except="$DIST" \
  --remote-debugging-address=127.0.0.1 \
  --remote-debugging-port="$CDP_PORT" \
  --no-first-run \
  --no-default-browser-check \
  "$START_URL"

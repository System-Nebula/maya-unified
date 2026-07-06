#!/usr/bin/env bash
# Reset dashboard player + conversation for a clean batch test run.
set -euo pipefail

BASE="${MAYA_GATEWAY_URL:-http://localhost:8080}"
COOKIE="${MAYA_TEST_COOKIE:-}"

curl_args=(-sS -X POST)
if [[ -n "$COOKIE" ]]; then
  curl_args+=(-H "Cookie: $COOKIE")
fi

echo "Clearing player at $BASE/api/media/player/clear"
curl "${curl_args[@]}" "$BASE/api/media/player/clear" || true

echo "Clearing conversation at $BASE/api/voice/agent/conversation/clear?player=1"
curl "${curl_args[@]}" "$BASE/api/voice/agent/conversation/clear?player=1" || true

echo "Done. Restart the voice agent if you changed player tool code."

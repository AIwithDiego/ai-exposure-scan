#!/usr/bin/env bash
# Build the dashboard, start the fixture on :8765, then serve dashboard + scan API on :8000.
# PYTHON=path/to/python overrides python. Stops the fixture server on exit.
set -euo pipefail
cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python}"
FIXTURE_PORT=8765
APP_PORT=8000

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  echo "app: $PYTHON not found. Install Python 3.11+ or set PYTHON=/path/to/python." >&2
  exit 1
fi
if ! "$PYTHON" -c "import playwright" 2>/dev/null; then
  echo "app: playwright isn't installed for $PYTHON. Run: $PYTHON -m pip install -r requirements.txt" >&2
  exit 1
fi
if ! "$PYTHON" -c "
import os, sys
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    sys.exit(0 if os.path.exists(p.chromium.executable_path) else 1)
" 2>/dev/null; then
  echo "app: Playwright's Chromium isn't installed. Run: $PYTHON -m playwright install chromium" >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "app: npm not found. Install Node 18+ to build the dashboard." >&2
  exit 1
fi
for port in "$FIXTURE_PORT" "$APP_PORT"; do
  if ! "$PYTHON" -c "import socket, sys; sys.exit(socket.socket().connect_ex(('127.0.0.1', $port)) == 0)"; then
    echo "app: port $port is already in use. Stop whatever is running there (e.g. an old fixture server) and try again." >&2
    exit 1
  fi
done

(cd dashboard && npm install && npm run build)

"$PYTHON" -m http.server "$FIXTURE_PORT" --directory fixtures/cafe-demo >/dev/null 2>&1 &
FIXTURE_PID=$!
trap 'kill "$FIXTURE_PID" 2>/dev/null || true' EXIT

echo
echo "Open http://localhost:$APP_PORT  (scan localhost:$FIXTURE_PORT for the demo café; Ctrl-C to stop)"
# Not exec: the EXIT trap has to survive to stop the fixture server.
"$PYTHON" -m scan serve --port "$APP_PORT" --allow-fixture

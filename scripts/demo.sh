#!/usr/bin/env bash
# Fixture server on :8765 -> scan all -> dashboard dev server. Stops the fixture server on exit.
# SITES=path/to/list.txt overrides data/sites.txt.
set -euo pipefail
cd "$(dirname "$0")/.."

python -m http.server 8765 --directory fixtures/cafe-demo >/dev/null 2>&1 &
FIXTURE_PID=$!
trap 'kill "$FIXTURE_PID" 2>/dev/null || true' EXIT
sleep 1

python -m scan all --sites "${SITES:-data/sites.txt}"
cd dashboard && npm run dev

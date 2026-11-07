#!/usr/bin/env bash
# Fixture server on :8765 -> scan all -> dashboard dev server. Stops the fixture server on exit.
# SITES=path/to/list.txt overrides data/sites.txt. PYTHON=path/to/python overrides python3.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python3}"
PORT=8765

if ! "$PY" -c "import socket, sys; sys.exit(socket.socket().connect_ex(('127.0.0.1', $PORT)) == 0)"; then
  echo "demo: port $PORT is already in use. Stop whatever is running there (e.g. an old fixture server) and try again." >&2
  exit 1
fi

"$PY" -m http.server "$PORT" --directory fixtures/cafe-demo >/dev/null 2>&1 &
FIXTURE_PID=$!
trap 'kill "$FIXTURE_PID" 2>/dev/null || true' EXIT

if ! "$PY" - "$PORT" <<'PYCHECK'
import sys, time, urllib.request
url = f"http://localhost:{sys.argv[1]}/llms.txt"
for _ in range(20):
    try:
        if "Bella" in urllib.request.urlopen(url, timeout=2).read().decode("utf-8", "replace"):
            sys.exit(0)
    except OSError:
        pass
    time.sleep(0.5)
sys.exit(1)
PYCHECK
then
  echo "demo: the fixture server didn't come up: $(printf 'http://localhost:%s/llms.txt' "$PORT") doesn't contain \"Bella\"." >&2
  exit 1
fi

"$PY" -m scan all --sites "${SITES:-data/sites.txt}"
cd dashboard && npm run dev

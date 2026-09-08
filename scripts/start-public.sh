#!/usr/bin/env bash
# Start gatekeeper + Tailscale Funnel (fixed public URL, offline page when app down).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if ! command -v tailscale >/dev/null 2>&1; then
  echo "Install Tailscale first: brew install tailscale"
  echo "Then open the Tailscale app and sign in. See TAILSCALE.md"
  exit 1
fi

if ! tailscale status >/dev/null 2>&1; then
  echo "Tailscale is not connected."
  echo "Open the Tailscale app and sign in, or run: tailscale up"
  exit 1
fi

mkdir -p .run

if lsof -ti:8000 >/dev/null 2>&1; then
  echo "Port 8000 already in use (gatekeeper may already be running)."
else
  nohup uv run uvicorn tickets.gatekeeper:app --host 127.0.0.1 --port 8000 > .run/gatekeeper.log 2>&1 &
  echo $! > .run/gatekeeper.pid
  sleep 1
  echo "Gatekeeper started on :8000 (pid $(cat .run/gatekeeper.pid))"
  echo "Log: .run/gatekeeper.log"
fi

if tailscale funnel status 2>/dev/null | grep -qE '8000|127\.0\.0\.1:8000|localhost:8000'; then
  echo "Tailscale Funnel already exposing port 8000."
else
  # Background funnel to local gatekeeper (public HTTPS edge on ts.net).
  tailscale funnel --bg 8000
  echo "Tailscale Funnel started for port 8000."
fi

echo ""
./scripts/show-public-url.sh
echo ""
echo "Live the ticket app with: ./scripts/live-app.sh"
echo "Stop app only (offline page): ./scripts/stop-app.sh"

#!/usr/bin/env bash
# Cloudflare named tunnel (requires your own domain). Prefer TAILSCALE.md for free setup.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -f cloudflared/config.yml ]]; then
  echo "Missing cloudflared/config.yml — see CLOUDFLARE_TUNNEL.md"
  exit 1
fi

mkdir -p .run

if lsof -ti:8000 >/dev/null 2>&1; then
  echo "Port 8000 already in use (gatekeeper may already be running)."
else
  uv run uvicorn tickets.gatekeeper:app --host 0.0.0.0 --port 8000 &
  echo $! > .run/gatekeeper.pid
  echo "Gatekeeper started on :8000 (pid $(cat .run/gatekeeper.pid))"
fi

if pgrep -f "cloudflared tunnel.*run sme-tickets" >/dev/null 2>&1; then
  echo "Cloudflare tunnel already running."
else
  cloudflared tunnel --config cloudflared/config.yml run sme-tickets &
  echo $! > .run/tunnel.pid
  echo "Cloudflare tunnel started (pid $(cat .run/tunnel.pid))"
fi

echo ""
echo "Public entry is up. Live the app with: ./scripts/live-app.sh"
echo "Fixed URL is in cloudflared/config.yml (hostname)."

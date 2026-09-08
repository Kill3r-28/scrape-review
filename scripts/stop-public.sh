#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

./scripts/stop-app.sh

if [[ -f .run/gatekeeper.pid ]]; then
  kill "$(cat .run/gatekeeper.pid)" 2>/dev/null || true
  rm -f .run/gatekeeper.pid
fi

if command -v tailscale >/dev/null 2>&1; then
  tailscale funnel reset 2>/dev/null || true
fi

lsof -ti:8000 | xargs kill -9 2>/dev/null || true
echo "Gatekeeper and Tailscale Funnel stopped."

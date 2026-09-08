#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
mkdir -p .run

if lsof -ti:8001 >/dev/null 2>&1; then
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
  echo "Ticket app already running on :8001"
  if [[ -n "${LAN_IP:-}" ]]; then
    echo "Same-WiFi link: http://${LAN_IP}:8001"
  fi
  exit 0
fi

exec uv run python scripts/start-lan.py

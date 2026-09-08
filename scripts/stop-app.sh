#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f .run/app.pid ]]; then
  kill "$(cat .run/app.pid)" 2>/dev/null || true
  rm -f .run/app.pid
fi
lsof -ti:8001 | xargs kill -9 2>/dev/null || true
echo "Ticket app stopped. Public URL now shows the offline page."

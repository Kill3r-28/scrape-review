#!/usr/bin/env bash
# Print the stable Tailscale Funnel URL for this machine (if funnel is active).
set -euo pipefail

if ! command -v tailscale >/dev/null 2>&1; then
  echo "Tailscale not installed. Run: brew install tailscale"
  exit 1
fi

if ! tailscale status >/dev/null 2>&1; then
  echo "Tailscale is not connected. Open the Tailscale app and sign in, or run: tailscale up"
  exit 1
fi

echo "Tailscale Funnel status:"
tailscale funnel status 2>&1 || true

DNS=$(tailscale status --json 2>/dev/null | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    self = d.get('Self', {})
    dns = self.get('DNSName', '').rstrip('.')
    print(dns)
except Exception:
    pass
" 2>/dev/null || true)

if [[ -n "${DNS:-}" ]]; then
  echo ""
  echo "Your stable public URL (when ./scripts/start-public.sh is running):"
  echo "  https://${DNS}"
fi

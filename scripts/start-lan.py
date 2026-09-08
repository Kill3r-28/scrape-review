#!/usr/bin/env python3
"""Start ticket app on LAN (0.0.0.0:8001) in a detached session."""
from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUN = ROOT / ".run"
PORT = 8001


def lan_ip() -> str:
    for iface in ("en0", "en1"):
        try:
            out = subprocess.check_output(["ipconfig", "getifaddr", iface], text=True).strip()
            if out:
                return out
        except subprocess.CalledProcessError:
            pass
    return ""


def main() -> int:
    RUN.mkdir(exist_ok=True)
    subprocess.run(
        ["uv", "run", "python", "-m", "tickets.jobs.agent_cli", "--apply-not-mine-feedback"],
        cwd=ROOT,
        check=False,
    )
    log = (RUN / "app.log").open("w")
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "tickets.app:app", "--host", "0.0.0.0", "--port", str(PORT)],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    (RUN / "app.pid").write_text(str(proc.pid))
    time.sleep(2)
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5) as resp:
            resp.read()
    except OSError as exc:
        print(f"App failed to start: {exc}", file=sys.stderr)
        return 1
    ip = lan_ip()
    print(f"Ticket app live on :{PORT} (pid {proc.pid})")
    if ip:
        print(f"Same-WiFi link: http://{ip}:{PORT}")
    else:
        print(f"Same-WiFi link: http://<your-mac-ip>:{PORT}")
    print("If phones cannot connect: System Settings → Network → Firewall → allow Python.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

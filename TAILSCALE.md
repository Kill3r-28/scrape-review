# Tailscale Funnel — fixed public URL (free, no domain)

Use this for a **permanent SME link** like:

`https://your-macbook.your-tailnet.ts.net`

No domain purchase. Free personal Tailscale account.

When the ticket app is **not** running, that URL shows an offline page. When you **live** the app, the same URL serves the full board.

## Architecture

```
SME browser → https://YOUR-MACHINE.YOUR-TAILNET.ts.net (fixed)
           → Tailscale Funnel (HTTPS)
           → gatekeeper :8000 on your laptop
                 ├─ app live on :8001 → proxy to ticket app
                 └─ app down          → offline.html
```

## One-time setup

### 1. Install Tailscale

**Option A — menu bar app (recommended on Mac):**

```bash
brew install --cask tailscale-app
```

Open **Tailscale** from Applications and sign in (Google/GitHub/email).

**Option B — CLI only:**

```bash
brew install tailscale
sudo brew services start tailscale
tailscale up
```

Follow the login link printed in the terminal.

### 2. Enable Funnel (first time only)

The first time you run `./scripts/start-public.sh`, Tailscale may open a browser to approve **Funnel** for your tailnet. Click **Allow**.

You can also enable it manually:

```bash
tailscale funnel status
```

### 3. Install Python deps

```bash
uv sync
```

### 4. Save your public URL

After `./scripts/start-public.sh`, run:

```bash
./scripts/show-public-url.sh
```

Copy that URL and share it with SMEs — it stays the same every time (unless you rename your Mac in Tailscale).

## Daily use

**Terminal 1 — public entry (keep running):**

```bash
./scripts/start-public.sh
./scripts/show-public-url.sh   # copy link for SMEs
```

**Terminal 2 — live the app:**

```bash
./scripts/live-app.sh
```

**Stop app only (offline page on same URL):**

```bash
./scripts/stop-app.sh
```

**Stop everything:**

```bash
./scripts/stop-public.sh
```

## Ports

| Port | Service |
|------|---------|
| 8000 | Gatekeeper (Funnel points here) |
| 8001 | Ticket app (internal, only when "live") |

## Notes

- Resolved tickets and notes persist in `tickets.db` on your laptop.
- If the laptop sleeps or you run `stop-public.sh`, the URL won't load until you start public entry again.
- Tailscale Funnel is for **non-commercial / internal team use** on the free personal plan — fine for SME ticket triage.
- Cloudflare named tunnel (custom domain) is still documented in `CLOUDFLARE_TUNNEL.md` if you switch later.

## Troubleshooting

**`tailscale: command not found`** — run `brew install tailscale` and open the app once.

**Funnel not enabled** — visit [login.tailscale.com/admin/acls](https://login.tailscale.com/admin/acls) and ensure your user can use funnel, or approve when prompted.

**URL shows offline but app should be live** — run `./scripts/live-app.sh` and check `curl http://127.0.0.1:8001/health`.

**Wrong URL after Mac rename** — run `./scripts/show-public-url.sh` again.

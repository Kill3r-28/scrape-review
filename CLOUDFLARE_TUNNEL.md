# Cloudflare named tunnel — fixed public URL (custom domain)

> **Easier free option:** use [Tailscale Funnel](TAILSCALE.md) — no domain purchase required.

Use this when you want **one permanent link** for SMEs (e.g. `https://sme-tickets.yourdomain.com`).

When the ticket app is **not** running, that URL shows an offline page: *"Not live right now — ask admin to start the app."*

When you **live** the app, the same URL serves the full ticket board.

## Architecture

```
SME browser → sme-tickets.yourdomain.com (fixed)
           → Cloudflare named tunnel
           → gatekeeper :8000 on your laptop
                 ├─ app live on :8001 → proxy to ticket app
                 └─ app down          → offline.html
```

## One-time setup

### 1. Prerequisites

- A domain on Cloudflare (free plan is fine)
- [cloudflared](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) installed

```bash
brew install cloudflared   # macOS
```

### 2. Log in and create tunnel

```bash
cd /path/to/scrape-review

cloudflared tunnel login
cloudflared tunnel create sme-tickets
```

Note the tunnel ID printed. Credentials land in `~/.cloudflared/<TUNNEL_ID>.json`.

Copy credentials into the repo (gitignored):

```bash
mkdir -p .cloudflared
cp ~/.cloudflared/<TUNNEL_ID>.json .cloudflared/
```

### 3. DNS route

Pick a hostname, e.g. `sme-tickets.yourdomain.com`:

```bash
cloudflared tunnel route dns sme-tickets sme-tickets.yourdomain.com
```

### 4. Config file

```bash
cp cloudflared/config.yml.example cloudflared/config.yml
```

Edit `cloudflared/config.yml`:

- `credentials-file`: `.cloudflared/<TUNNEL_ID>.json`
- `hostname`: your chosen subdomain

### 5. Install deps

```bash
uv sync
```

## Daily use

**Terminal 1 — public entry (keep running):**

```bash
./scripts/start-public.sh
```

Starts gatekeeper (`:8000`) + Cloudflare named tunnel. SMEs can open your fixed URL anytime; they'll see the offline page until you live the app.

**Terminal 2 — live the app (when SMEs should work tickets):**

```bash
./scripts/live-app.sh
```

Starts the ticket app on internal port `:8001`. Same public URL now serves the full app.

**Stop app only (keep public URL + offline page):**

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
| 8000 | Gatekeeper (tunnel points here) |
| 8001 | Ticket app (internal, only when "live") |

## Notes

- Resolved tickets and notes persist in `tickets.db` on your laptop — same as before.
- The tunnel URL is **fixed**; only the app on/off state changes what SMEs see.
- If the laptop sleeps or you stop `start-public.sh`, the URL won't resolve until you start it again.

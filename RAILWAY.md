# Deploy on Railway (auto-deploy from GitHub)

This app is **one service**: FastAPI serves the API **and** the SME web UI (Jinja templates + static CSS/JS). You do **not** need a separate frontend deploy on Railway.

```
GitHub push (main) → Railway builds Dockerfile → Web service + Postgres
                              ↓
                    https://your-app.up.railway.app
```

## 1. Push this repo to GitHub

Repo: `https://github.com/Kill3r-28/scrape-review`

After adding Railway files, commit and push to `main`. Every push to the connected branch redeploys automatically.

## 2. Create Railway project

1. Go to [railway.app](https://railway.app) and sign in with **GitHub**.
2. **New Project** → **Deploy from GitHub repo** → choose `Kill3r-28/scrape-review`.
3. Railway detects the `Dockerfile` and deploys the web service.

## 3. Add Postgres

1. In the project canvas: **+ New** → **Database** → **PostgreSQL**.
2. Open the **web service** → **Variables** → **Add variable reference** → select Postgres `DATABASE_URL`.

Railway injects `DATABASE_URL`; the app converts `postgres://` to `postgresql://` on startup.

## 4. Required environment variables

Set these on the **web service** (not Postgres):

| Variable | Value |
|----------|--------|
| `SESSION_SECRET` | Long random string (e.g. `openssl rand -hex 32`) |
| `SESSION_SECURE` | `true` |
| `INGEST_TOKEN` | Long random secret for `/api/ingest/*` |
| `SCRAPER_USERNAME` | Topin Django admin username |
| `SCRAPER_PASSWORD` | Topin Django admin password |
| `ADMIN_PASSWORD` | (optional) override password for `admin` login |

`DATABASE_URL` comes from the Postgres plugin reference.

## 5. Public URL

1. Web service → **Settings** → **Networking** → **Generate domain**.
2. You get a URL like `https://scrape-review-production.up.railway.app`.

Share that with SMEs. No WiFi / Cloudflare / Tailscale needed.

## 6. GitHub auto-deploy

With the repo connected, **every push to `main` triggers a new deploy**.

- Service → **Settings** → confirm **Source Repo** is linked and branch is `main`.
- Optional: enable **Wait for CI** if you add test workflows later.

Manual redeploy: service → **Deployments** → **Redeploy**.

## 7. Daily ingest (GitHub Actions)

Railway does not run long cron jobs reliably on free tiers. Use the included workflow:

1. GitHub repo → **Settings → Secrets and variables → Actions**
2. Add:
   - `APP_URL` = your Railway URL (no trailing slash)
   - `INGEST_TOKEN` = same as Railway `INGEST_TOKEN`
3. Workflow: `.github/workflows/daily-ingest.yml` (09:00 IST daily)

Manual run: **Actions → daily-ticket-ingest → Run workflow**.

## 8. One-time ticket backfill

From your laptop against production Postgres:

```bash
export DATABASE_URL='postgresql://...'   # from Railway Postgres
export SCRAPER_USERNAME='...'
export SCRAPER_PASSWORD='...'
uv run python -m tickets.jobs.ingest_cli --from-date 2026-08-01 --to-date 2026-09-02
uv run python -m tickets.jobs.agent_cli --assign-criticality
```

## 9. Default logins

See main `README.md`. Change passwords after first login (`ADMIN_PASSWORD` env overrides admin on seed).

## Notes

- **Single app** — backend + frontend in one container; no second Railway service.
- **Persistent data** lives in Postgres, not the container filesystem.
- **Do not commit** `.env` or `tickets.db`.
- First deploy runs `init_db()` on startup (tables + seed users + assignment rules).

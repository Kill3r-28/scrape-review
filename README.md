# Scrape Review + SME Tickets

Scrapes Topin/Django admin student reports, stores each report as a **ticket**, routes GRIT programme assessments to SMEs, and serves a hosted resolution board.

## Ticket system (new)

Each student report becomes an open ticket with:

- **Student description**
- **Ticket status** (`open` / `in_progress` / `resolved`)
- **SME name** (auto-routed for GRIT titles; editable)

### GRIT routing

If `org_assessment_title` contains any of these (case-insensitive), programme = **GRIT** and subject is matched:

- Quantitative Reasoning
- CS Fundamentals
- UI Engineering
- Computational Thinking
- GenAI
- Critical Thinking & Communication
- Server Side Engineering
- SQL

SME names are configured in `tickets/config.py` (`SME_BY_SUBJECT`). Default is `Unassigned` until you fill real names.

### Run the UI locally

```bash
uv sync
uv run uvicorn tickets.app:app --reload --port 8000
```

Open http://127.0.0.1:8000

### Ingest yesterday's reports (9 AM job)

```bash
uv run python -m tickets.jobs.ingest_cli --previous-day
```

Optional: enrich with question text/tags (slower):

```bash
uv run python -m tickets.jobs.ingest_cli --previous-day --enrich
```

Specific date:

```bash
uv run python -m tickets.jobs.ingest_cli --date 2026-08-20
```

### Environment

```env
SCRAPER_USERNAME=...
SCRAPER_PASSWORD=...
DATABASE_URL=postgresql://...   # optional; defaults to local sqlite tickets.db
INGEST_TOKEN=...                # required in production for /api/ingest/*
OPENROUTER_API_KEY=...          # only for legacy LLM review flow
```

## Daily scrape — is it automatic?

**Not yet.** The ingest command exists (`python -m tickets.jobs.ingest_cli --previous-day`), but nothing runs it on a schedule until you deploy a **Railway cron** (or similar) at 09:00 IST. Until then, run ingest manually or set up that cron.

### Deploy on Render (recommended free host)

See **[DEPLOY_RENDER.md](DEPLOY_RENDER.md)** for the full steps:

1. Free Postgres on [Neon](https://neon.tech)
2. Render Blueprint from this repo (`render.yaml`)
3. GitHub Action for 9 AM IST daily ingest

### Deploy on Railway

Railway is optional/paid for most plans. Prefer Render + Neon for free hosting.

### Login accounts (change passwords after first login)

| Username | Password | Role |
|----------|----------|------|
| admin | Admin@Grit2026! | Admin (you) |
| poojitha | Poojitha@Grit2026! | SME — Quantitative Reasoning |
| viharika | Viharika@Grit2026! | SME — UI Engineering |
| varsha | Varsha@Grit2026! | SME — Computational Thinking, SQL |
| saifullah | Saifullah@Grit2026! | SME — CS Fundamentals, Server Side Engineering |
| namitha | Namitha@Grit2026! | SME — Critical Thinking & Communication |

GenAI GRIT tickets stay **Unassigned** until you map an SME. Non-GRIT tickets are always Unassigned (admin can assign).

## Legacy local LLM review flow

1. `uv run python main.py` — scrape + LLM MCQ review into `output/<date>/`
2. `uv run reflex run` — older Reflex SME dashboard (CSV-based)

The ticket board above is the path forward for continuous resolution.

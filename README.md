# SME Ticket Agent

Scrape student assessment reports into tickets, **assign SMEs from question topic tags**, **nudge SMEs by email**, and **draft WhatsApp replies per student** from SME notes.

## Agent loop

1. **Assign** — `TOPIC_*` tags → SME (rules, no LLM)
2. **Nudge** — daily 10:00 IST email: open ticket count this month per SME
3. **Draft** — LLM WhatsApp message per `user_id` from ticket notes (UI: `/whatsapp`)

## Topic → SME

| Topic signals | SME |
|---------------|-----|
| Quantitative, Logical | Poojitha Pachava |
| Verbal | Mariyam |
| HTML/CSS, React, Web, Node | Viharika |
| DSA, Coding, SQL, Python, CPP | Varsha |
| CS Fundamentals + other topics | Saifullah |
| No topic tags | Unassigned |

Edit emails in `tickets/config.py` → `SME_EMAILS` (required for real nudges).

## Run locally

```bash
uv sync
uv run uvicorn tickets.app:app --reload --port 8000
```

Open http://127.0.0.1:8000 — login `admin` / `Admin@Grit2026!`

### Ingest / enrich

```bash
uv run python -m tickets.jobs.ingest_cli --previous-day
uv run python -m tickets.jobs.ingest_cli --enrich-tickets
uv run python -m tickets.jobs.agent_cli --reassign
```

### Nudge (dry run)

```bash
uv run python -m tickets.jobs.agent_cli --nudge --dry-run
```

SMTP (when ready): `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`

### WhatsApp drafts

```bash
uv run python -m tickets.jobs.agent_cli --draft-whatsapp
# or --user-id <uuid> --no-llm
```

Needs `OPENROUTER_API_KEY` for LLM drafts (falls back to a template if missing).

### Evals

```bash
uv run python evals/agent/run_evals.py
```

Gold sets: `evals/agent/assign_cases.json` and `evals/agent/critical_remark_cases.json`.

## Env

```env
SCRAPER_USERNAME=...
SCRAPER_PASSWORD=...
OPENROUTER_API_KEY=...          # WhatsApp drafts only
OPENROUTER_MODEL=deepseek/deepseek-chat-v3.1
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=
```

## Logins

| User | Password | Role |
|------|----------|------|
| admin | Admin@Grit2026! | Admin |
| poojitha | Poojitha@Grit2026! | SME |
| mariyam | Mariyam@Grit2026! | SME |
| viharika | Viharika@Grit2026! | SME |
| varsha | Varsha@Grit2026! | SME |
| saifullah | Saifullah@Grit2026! | SME |

Deploy notes: see `DEPLOY_RENDER.md` when you are ready to host.

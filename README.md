# Scrape Review

This project scrapes Topin/Django admin report data for a date, reviews MCQ content issues with an LLM, and provides a local Reflex dashboard for SME follow-up.

## What it does

1. `main.py` asks for a date in `dd-mm-yyyy`
2. `scrape.py` logs into the admin site using `.env` credentials
3. It scrapes report rows matching the input date
4. It saves them to `output/<date>/all_reports.csv`
5. `review.py` reads that CSV and filters MCQ questions
6. It fetches MCQ options, marked correct option, and question tags from Django admin
7. DeepSeek via OpenRouter reviews each MCQ complaint
8. It writes `output/<date>/to_review_mcq.csv`
9. The Reflex dashboard reads local output files for SME follow-up

## Project structure

```text
scrape-review/
  main.py
  scrape.py
  review.py
  prompts.md
  rxconfig.py
  dashboard/
  evals/
  output/
```

## Required environment variables

Create a `.env` file in the project root.

```env
SCRAPER_USERNAME=your_admin_username
SCRAPER_PASSWORD=your_admin_password
OPENROUTER_API_KEY=your_openrouter_key
OPENROUTER_MODEL=deepseek/deepseek-chat-v3.1
OPENROUTER_REFERER=http://localhost
OPENROUTER_TITLE=scrape-review
```

## Run scrape + review

```bash
uv run python main.py
```

You will be prompted for a date like:

```text
26-06-2026
```

## Reflex SME dashboard

Run the dashboard with:

```bash
uv run reflex run
```

The dashboard is open without authentication for now. It reads local files from:

```text
output/<date>/to_review_mcq.csv
```

It shows a calendar view with resolved and not-resolved counts per date. Clicking a date opens the MCQ reports for that date, including user id, question id, and question tags from scraped data. SME, status, and notes are saved locally to:

```text
output/<date>/sme_status.csv
```

## Output structure

Each run uses one folder per date.

```text
output/
  26-06-2026/
    all_reports.csv
    to_review_mcq.csv
    sme_status.csv
    log.txt
```

## Resume behavior

The workflow is resumable.

- If `all_reports.csv` already exists, scraping is skipped
- If `to_review_mcq.csv` already has rows, MCQ review continues from where it stopped
- Human dashboard updates are stored separately in `sme_status.csv`

## Prompt management

All LLM prompts are stored in `prompts.md`.
`review.py` loads prompt text from there instead of hardcoding large prompts.

## Evals

The `evals/` folder is for example-based checks. Add positives, negatives, and false positives there to improve prompt quality over time.

## Notes

- Scraping uses `requests` + `BeautifulSoup`, not browser automation
- The current LLM backend is OpenRouter
- The default review model is DeepSeek
- The review flow currently handles MCQs only, with room to add coding/SQL review files later

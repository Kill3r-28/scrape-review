"""CLI for daily / range ticket ingest (Railway cron / local)."""

from __future__ import annotations

import argparse
from datetime import date

from scrape import ENV_PATH, load_dotenv
from tickets.db import SessionLocal, init_db
from tickets.ingest import (
    apply_sme_routing,
    enrich_existing_tickets,
    ingest_date,
    ingest_date_range,
    ingest_previous_day,
    repair_missing_question_data,
)


def main() -> int:
    load_dotenv(ENV_PATH)
    parser = argparse.ArgumentParser(description="Ingest student reports as tickets")
    parser.add_argument("--previous-day", action="store_true")
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--from-date", help="Range start YYYY-MM-DD")
    parser.add_argument("--to-date", help="Range end YYYY-MM-DD")
    parser.add_argument("--enrich", action="store_true")
    parser.add_argument("--no-enrich", action="store_true")
    parser.add_argument(
        "--reroute-smes",
        action="store_true",
        help="Re-apply GRIT subject → SME mapping on existing tickets",
    )
    parser.add_argument(
        "--enrich-tickets",
        action="store_true",
        help="Backfill question type/text/tags for tickets with a question_id",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional limit for --enrich-tickets",
    )
    parser.add_argument(
        "--repair-questions",
        action="store_true",
        help="Re-scrape and fill missing question_id/type/text/tags "
        "(uses --from-date/--to-date)",
    )
    args = parser.parse_args()

    enrich = True
    if args.no_enrich:
        enrich = False
    if args.enrich:
        enrich = True

    init_db()
    db = SessionLocal()
    try:
        if args.reroute_smes:
            updated = apply_sme_routing(db)
            print(f"Re-routed SME assignment on {updated} tickets")
            return 0

        if args.repair_questions:
            if not args.from_date or not args.to_date:
                parser.error("--repair-questions requires --from-date and --to-date")
                return 2
            start = date.fromisoformat(args.from_date)
            end = date.fromisoformat(args.to_date)
            result = repair_missing_question_data(db, start, end, enrich=enrich)
            print(
                f"Repair complete: scraped={result['scraped_rows']} "
                f"linked={result['question_ids_linked']} "
                f"enriched={result['enriched']}"
            )
            return 0

        if args.enrich_tickets:
            result = enrich_existing_tickets(db, only_missing=True, limit=args.limit)
            print(
                f"Enrich complete: updated={result['updated']} "
                f"skipped={result['skipped']} total={result['total']}"
            )
            return 0

        if args.previous_day:
            result = ingest_previous_day(db, enrich=enrich)
            print(
                f"Ingest complete for {result.get('report_date')}: "
                f"created={result['created']} skipped={result['skipped']} "
                f"rows={result['total_rows']}"
            )
        elif args.from_date and args.to_date:
            start = date.fromisoformat(args.from_date)
            end = date.fromisoformat(args.to_date)
            result = ingest_date_range(db, start, end, enrich=enrich)
            print(
                f"Ingest complete for {result['start_date']} → {result['end_date']}: "
                f"created={result['created']} skipped={result['skipped']} "
                f"rows={result['total_rows']}"
            )
        elif args.date:
            target = date.fromisoformat(args.date)
            result = ingest_date(db, target, enrich=enrich)
            result["report_date"] = target.isoformat()
            print(
                f"Ingest complete for {result.get('report_date')}: "
                f"created={result['created']} skipped={result['skipped']} "
                f"rows={result['total_rows']}"
            )
        else:
            parser.error("Provide --previous-day, --date, or --from-date/--to-date")
            return 2
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

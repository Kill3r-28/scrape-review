"""CLI for daily / range ticket ingest (Railway cron / local)."""

from __future__ import annotations

import argparse
from datetime import date

from scrape import ENV_PATH, load_dotenv
from tickets.db import SessionLocal, init_db
from tickets.ingest import apply_sme_routing, ingest_date, ingest_date_range, ingest_previous_day


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
    args = parser.parse_args()

    enrich = bool(args.enrich) and not args.no_enrich
    if not args.enrich and not args.no_enrich:
        enrich = False

    init_db()
    db = SessionLocal()
    try:
        if args.reroute_smes:
            updated = apply_sme_routing(db)
            print(f"Re-routed SME assignment on {updated} tickets")
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

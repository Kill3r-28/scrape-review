"""CLI for agent jobs: nudge SMEs, draft WhatsApp messages."""

from __future__ import annotations

import argparse
import json

from scrape import ENV_PATH, load_dotenv
from tickets.agent.criticality import assign_criticality_all
from tickets.agent.draft import draft_whatsapp_for_user, draft_whatsapp_for_users_with_notes
from tickets.agent.nudge import run_daily_sme_nudges
from tickets.db import SessionLocal, init_db
from tickets.ingest import apply_sme_routing


def main() -> int:
    load_dotenv(ENV_PATH)
    parser = argparse.ArgumentParser(description="SME ticket agent jobs")
    parser.add_argument("--nudge", action="store_true", help="Email SMEs open-count for this month")
    parser.add_argument("--dry-run", action="store_true", help="Do not send emails")
    parser.add_argument(
        "--draft-whatsapp",
        action="store_true",
        help="Draft WhatsApp messages for all user_ids with SME notes",
    )
    parser.add_argument("--user-id", help="Draft for a single student user_id")
    parser.add_argument("--no-llm", action="store_true", help="Template draft only")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reassign", action="store_true", help="Re-apply topic-tag SME assignment")
    parser.add_argument(
        "--assign-criticality",
        action="store_true",
        help="Classify all tickets as Critical / Moderate / Trivial",
    )
    parser.add_argument(
        "--only-missing-criticality",
        action="store_true",
        help="With --assign-criticality, skip tickets that already have a label",
    )
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    try:
        if args.reassign:
            n = apply_sme_routing(db)
            print(f"Reassigned {n} tickets from topic tags")
            return 0
        if args.assign_criticality:
            result = assign_criticality_all(
                db, only_missing=args.only_missing_criticality
            )
            print(
                "Criticality assigned: "
                f"updated={result['updated']} "
                f"critical={result['Critical']} "
                f"moderate={result['Moderate']} "
                f"trivial={result['Trivial']}"
            )
            return 0
        if args.nudge:
            results = run_daily_sme_nudges(db, dry_run=args.dry_run)
            print(json.dumps(results, indent=2))
            return 0
        if args.draft_whatsapp or args.user_id:
            use_llm = not args.no_llm
            if args.user_id:
                draft = draft_whatsapp_for_user(db, args.user_id, use_llm=use_llm)
                print(f"Drafted user_id={draft.user_id} tickets={draft.ticket_ids}")
                print(draft.message_text)
            else:
                drafts = draft_whatsapp_for_users_with_notes(
                    db, use_llm=use_llm, limit=args.limit
                )
                print(f"Drafted {len(drafts)} WhatsApp message(s)")
            return 0
        parser.error("Provide --nudge, --draft-whatsapp / --user-id, --reassign, or --assign-criticality")
        return 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

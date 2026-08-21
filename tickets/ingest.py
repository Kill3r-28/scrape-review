from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from scrape import (
    ENV_PATH,
    create_session,
    enrich_rows,
    load_dotenv,
    login_with_django_admin,
    parse_creation_datetime,
    scrape_reports_for_date,
    scrape_reports_for_date_range,
)
from tickets.config import STATUS_OPEN, STATUS_RESOLVED
from tickets.models import Ticket
from tickets.routing import route_ticket

IST = ZoneInfo("Asia/Kolkata")


def build_external_report_id(row: dict[str, str]) -> str:
    org_id = row.get("Org assessment id", "").strip()
    user_id = row.get("User id", "").strip()
    created = row.get("Creation datetime", "").strip()
    description = row.get("Description", "").strip()
    if org_id and user_id and created:
        raw = f"{org_id}|{user_id}|{created}|{description}"
    else:
        raw = "|".join(
            [
                org_id,
                user_id,
                created,
                description,
                row.get("Question id", "").strip(),
            ]
        )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:24]


def report_date_for_row(row: dict[str, str], fallback: date | None = None) -> date:
    parsed = parse_creation_datetime(row.get("Creation datetime", ""))
    if parsed:
        return parsed.date()
    if fallback:
        return fallback
    return datetime.now(IST).date()


def row_to_ticket_fields(row: dict[str, str], report_date: date) -> dict:
    title = row.get("Org assessment title", "").strip()
    routed = route_ticket(title)
    return {
        "external_report_id": build_external_report_id(row),
        "student_description": row.get("Description", "").strip(),
        "status": STATUS_OPEN,
        "sme_name": routed["sme_name"],
        "org_assessment_id": row.get("Org assessment id", "").strip(),
        "org_assessment_title": title,
        "programme": routed["programme"],
        "subject": routed["subject"],
        "user_id": row.get("User id", "").strip(),
        "category": row.get("Category", "").strip(),
        "sub_category": row.get("Sub category", "").strip(),
        "question_id": row.get("Question id", "").strip(),
        "question_type": row.get("Question type", "").strip(),
        "question_text": row.get("Question text", "").strip(),
        "question_tags": row.get("Question tags", "").strip(),
        "report_date": report_date.isoformat(),
        "creation_datetime": row.get("Creation datetime", "").strip(),
    }


def upsert_tickets(
    db: Session,
    rows: list[dict[str, str]],
    report_date: date | None = None,
) -> dict[str, int]:
    created = 0
    skipped = 0
    seen: set[str] = set()
    for row in rows:
        day = report_date_for_row(row, report_date)
        fields = row_to_ticket_fields(row, day)
        external_id = fields["external_report_id"]
        if external_id in seen:
            skipped += 1
            continue
        seen.add(external_id)
        existing = (
            db.query(Ticket)
            .filter(Ticket.external_report_id == external_id)
            .one_or_none()
        )
        if existing:
            skipped += 1
            continue
        db.add(Ticket(**fields))
        created += 1
        if created % 100 == 0:
            db.flush()
    db.commit()
    return {"created": created, "skipped": skipped, "total_rows": len(rows)}


def apply_sme_routing(db: Session) -> int:
    """Re-apply GRIT subject → SME mapping on all tickets."""
    updated = 0
    for ticket in db.query(Ticket).all():
        routed = route_ticket(ticket.org_assessment_title)
        changed = (
            ticket.programme != routed["programme"]
            or ticket.subject != routed["subject"]
            or ticket.sme_name != routed["sme_name"]
        )
        if not changed:
            continue
        ticket.programme = routed["programme"]
        ticket.subject = routed["subject"]
        ticket.sme_name = routed["sme_name"]
        updated += 1
    db.commit()
    return updated


def ingest_date(db: Session, target_date: date, *, enrich: bool = True) -> dict[str, int]:
    load_dotenv(ENV_PATH)
    rows = scrape_reports_for_date(target_date)
    if enrich and rows:
        session = create_session()
        login_with_django_admin(session)
        rows = enrich_rows(session, rows)
    return upsert_tickets(db, rows, target_date)


def ingest_date_range(
    db: Session,
    start_date: date,
    end_date: date,
    *,
    enrich: bool = False,
) -> dict[str, int]:
    load_dotenv(ENV_PATH)
    rows = scrape_reports_for_date_range(start_date, end_date)
    if enrich and rows:
        session = create_session()
        login_with_django_admin(session)
        rows = enrich_rows(session, rows)
    result = upsert_tickets(db, rows)
    result["start_date"] = start_date.isoformat()
    result["end_date"] = end_date.isoformat()
    return result


def ingest_previous_day(db: Session, *, enrich: bool = True) -> dict[str, int]:
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    result = ingest_date(db, yesterday, enrich=enrich)
    result["report_date"] = yesterday.isoformat()
    return result


def set_ticket_status(db: Session, ticket: Ticket, status: str) -> Ticket:
    ticket.status = status
    if status == STATUS_RESOLVED:
        ticket.resolved_at = datetime.now(IST)
    else:
        ticket.resolved_at = None
    db.commit()
    db.refresh(ticket)
    return ticket

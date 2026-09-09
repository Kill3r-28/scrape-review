from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from scrape import (
    ENV_PATH,
    create_session,
    enrich_rows,
    fetch_question_summary,
    fetch_question_tags,
    load_dotenv,
    login_with_django_admin,
    parse_creation_datetime,
    scrape_reports_for_date,
    scrape_reports_for_date_range,
)
from tickets.calendar_view import parse_iso_date
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


def row_to_ticket_fields(
    row: dict[str, str], report_date: date, db: Session | None = None
) -> dict:
    title = row.get("Org assessment title", "").strip()
    tags = row.get("Question tags", "").strip()
    routed = route_ticket(title, tags, db)
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
        "question_tags": tags,
        "report_date": report_date.isoformat(),
        "creation_datetime": row.get("Creation datetime", "").strip(),
    }


def upsert_tickets(
    db: Session,
    rows: list[dict[str, str]],
    report_date: date | None = None,
) -> dict[str, int]:
    created = 0
    updated = 0
    skipped = 0
    seen: set[str] = set()
    for row in rows:
        day = report_date_for_row(row, report_date)
        fields = row_to_ticket_fields(row, day, db)
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
            if _fill_missing_question_fields(existing, fields, db):
                updated += 1
            else:
                skipped += 1
            continue
        db.add(Ticket(**fields))
        created += 1
        if created % 100 == 0:
            db.flush()
    db.commit()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "total_rows": len(rows),
    }


def _fill_missing_question_fields(
    ticket: Ticket, fields: dict, db: Session | None = None
) -> bool:
    """
    Fill empty question_id / type / text / tags (and title) from scraped fields.
    Re-routes SME when tags land. Returns True if anything changed.
    """
    changed = False
    qid = (fields.get("question_id") or "").strip()
    if qid and not (ticket.question_id or "").strip():
        ticket.question_id = qid
        changed = True

    for key in ("question_type", "question_text", "question_tags"):
        new_val = (fields.get(key) or "").strip()
        if new_val and not (getattr(ticket, key) or "").strip():
            setattr(ticket, key, new_val)
            changed = True

    title = (fields.get("org_assessment_title") or "").strip()
    if title and not (ticket.org_assessment_title or "").strip():
        ticket.org_assessment_title = title
        changed = True

    org_id = (fields.get("org_assessment_id") or "").strip()
    if org_id and not (ticket.org_assessment_id or "").strip():
        ticket.org_assessment_id = org_id
        changed = True

    if changed:
        routed = route_ticket(ticket.org_assessment_title, ticket.question_tags, db)
        if ticket.programme != routed["programme"]:
            ticket.programme = routed["programme"]
        if ticket.subject != routed["subject"]:
            ticket.subject = routed["subject"]
        if (ticket.sme_name or "Unassigned") == "Unassigned":
            ticket.sme_name = routed["sme_name"]
    return changed


def apply_sme_routing(db: Session) -> int:
    """Re-apply programme + topic/title SME mapping (skips Not mine)."""
    from tickets.routing import reassign_open_tickets

    return reassign_open_tickets(db, skip_not_mine=True)


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


def enrich_existing_tickets(
    db: Session,
    *,
    only_missing: bool = True,
    limit: int | None = None,
) -> dict[str, int]:
    """Backfill question type/text/tags for tickets that already have a question_id."""
    load_dotenv(ENV_PATH)
    query = db.query(Ticket).filter(Ticket.question_id != "")
    if only_missing:
        query = query.filter(
            (Ticket.question_type == "")
            | (Ticket.question_text == "")
            | (Ticket.question_tags == "")
        )
    tickets = query.order_by(Ticket.id.asc()).all()
    if limit is not None:
        tickets = tickets[:limit]

    if not tickets:
        return {"updated": 0, "skipped": 0, "total": 0}

    session = create_session()
    login_with_django_admin(session)

    question_cache: dict[str, dict[str, str]] = {}
    tag_cache: dict[str, list[str]] = {}
    updated = 0
    skipped = 0
    total = len(tickets)

    for index, ticket in enumerate(tickets, start=1):
        qid = ticket.question_id.strip()
        print(f"\rEnriching ticket {index}/{total} ({qid})", end="", flush=True)

        if qid not in question_cache:
            question_cache[qid] = fetch_question_summary(session, qid)
        if qid not in tag_cache:
            tag_cache[qid] = fetch_question_tags(session, qid)

        summary = question_cache[qid]
        tags = tag_cache[qid]
        new_type = summary.get("Question type", "").strip()
        new_text = summary.get("Question text", "").strip()
        new_tags = ", ".join(tags)

        changed = False
        if new_type and ticket.question_type != new_type:
            ticket.question_type = new_type
            changed = True
        if new_text and ticket.question_text != new_text:
            ticket.question_text = new_text
            changed = True
        if new_tags and ticket.question_tags != new_tags:
            ticket.question_tags = new_tags
            changed = True

        # Re-assign SME when tags land/change.
        routed = route_ticket(
            ticket.org_assessment_title, ticket.question_tags or new_tags, db
        )
        if ticket.sme_name != routed["sme_name"]:
            ticket.sme_name = routed["sme_name"]
            changed = True
        if ticket.programme != routed["programme"]:
            ticket.programme = routed["programme"]
            changed = True
        if ticket.subject != routed["subject"]:
            ticket.subject = routed["subject"]
            changed = True

        if changed:
            updated += 1
        else:
            skipped += 1

        if index % 25 == 0:
            db.commit()

    db.commit()
    print()
    return {"updated": updated, "skipped": skipped, "total": total}


def repair_missing_question_data(
    db: Session,
    start_date: date,
    end_date: date,
    *,
    enrich: bool = True,
) -> dict[str, int]:
    """
    Re-scrape reports and fill question_id / type / text / tags on tickets that
    are missing them when the source report includes exam_details.questions_id.
    """
    load_dotenv(ENV_PATH)
    rows = scrape_reports_for_date_range(start_date, end_date)
    return _apply_scraped_rows_to_missing_question_tickets(db, rows, enrich=enrich)


def ensure_all_question_ids(db: Session, *, enrich: bool = True) -> dict[str, int]:
    """
    For every ticket with an empty question_id, re-scrape that ticket's report_date
    and fill question_id (plus type/text/tags) whenever the source has it.
    """
    load_dotenv(ENV_PATH)
    missing = (
        db.query(Ticket)
        .filter((Ticket.question_id == None) | (Ticket.question_id == ""))  # noqa: E711
        .order_by(Ticket.report_date.asc(), Ticket.id.asc())
        .all()
    )
    missing_before = len(missing)
    if not missing_before:
        return {
            "missing_before": 0,
            "dates_scraped": 0,
            "scraped_rows": 0,
            "question_ids_linked": 0,
            "still_missing": 0,
            "source_had_no_question_id": 0,
            "enriched": 0,
            "enrich_skipped": 0,
        }

    dates = sorted(
        {
            d
            for t in missing
            if (d := parse_iso_date(t.report_date or "")) is not None
        }
    )
    all_rows: list[dict[str, str]] = []
    for index, day in enumerate(dates, start=1):
        print(f"Repair scrape {index}/{len(dates)}: {day.isoformat()}", flush=True)
        all_rows.extend(scrape_reports_for_date(day))

    result = _apply_scraped_rows_to_missing_question_tickets(
        db, all_rows, enrich=enrich
    )
    still = (
        db.query(Ticket)
        .filter((Ticket.question_id == None) | (Ticket.question_id == ""))  # noqa: E711
        .count()
    )
    result["missing_before"] = missing_before
    result["dates_scraped"] = len(dates)
    result["still_missing"] = still
    result["source_had_no_question_id"] = int(result.get("matched_but_source_no_qid", 0))
    result["unmatched_missing"] = max(
        0, missing_before - int(result.get("matched_missing_tickets", 0))
    )
    return result


def _apply_scraped_rows_to_missing_question_tickets(
    db: Session,
    rows: list[dict[str, str]],
    *,
    enrich: bool,
) -> dict[str, int]:
    by_external = {build_external_report_id(row): row for row in rows}
    by_user_created_desc: dict[tuple[str, str, str], dict[str, str]] = {}
    by_user_org_created: dict[tuple[str, str, str], dict[str, str]] = {}
    by_user_desc_day: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        user = row.get("User id", "").strip()
        desc = row.get("Description", "").strip()
        created = row.get("Creation datetime", "").strip()
        org = row.get("Org assessment id", "").strip()
        parsed = parse_creation_datetime(created)
        day = parsed.date().isoformat() if parsed else ""
        if user and created:
            by_user_created_desc[(user, created, desc)] = row
        if user and org and created:
            by_user_org_created[(user, org, created)] = row
        if user and day:
            by_user_desc_day[(user, desc, day)] = row

    missing = db.query(Ticket).filter(
        (Ticket.question_id == None) | (Ticket.question_id == "")  # noqa: E711
    ).all()
    linked = 0
    matched_rows = 0
    matched_but_no_qid = 0
    for ticket in missing:
        row = by_external.get(ticket.external_report_id)
        if not row:
            row = by_user_created_desc.get(
                (ticket.user_id, ticket.creation_datetime, ticket.student_description)
            )
        if not row:
            row = by_user_org_created.get(
                (ticket.user_id, ticket.org_assessment_id, ticket.creation_datetime)
            )
        if not row:
            row = by_user_desc_day.get(
                (ticket.user_id, ticket.student_description, ticket.report_date or "")
            )
        if not row:
            continue
        matched_rows += 1
        fields = row_to_ticket_fields(
            row, report_date_for_row(row, parse_iso_date(ticket.report_date or "")), db
        )
        if not (fields.get("question_id") or "").strip():
            matched_but_no_qid += 1
            continue
        if _fill_missing_question_fields(ticket, fields, db):
            linked += 1
    db.commit()

    enrich_result = {"updated": 0, "skipped": 0, "total": 0}
    if enrich and linked:
        enrich_result = enrich_existing_tickets(db, only_missing=True)

    return {
        "scraped_rows": len(rows),
        "matched_missing_tickets": matched_rows,
        "matched_but_source_no_qid": matched_but_no_qid,
        "question_ids_linked": linked,
        "enriched": enrich_result["updated"],
        "enrich_skipped": enrich_result["skipped"],
    }

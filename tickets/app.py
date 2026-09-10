"""Ticket resolution web app."""

from __future__ import annotations

import os
from calendar import monthrange
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from tickets.auth import (
    User,
    authenticate,
    create_sme_user,
    is_admin,
    list_admin_sme_filters,
    list_assignable_smes,
)
from tickets.calendar_view import (
    build_calendar_days,
    month_title,
    parse_iso_date,
    shift_month,
)
from tickets.config import (
    ADMIN_SME_FILTERS,
    ASSIGNABLE_SMES,
    GRIT_SUBJECTS,
    PROGRAMME_GRIT,
    PROGRAMME_INTENSIVE_OFFLINE,
    PROGRAMME_NIAT_SKILL,
    ROLE_SME,
    RULE_TYPE_ASSESSMENT,
    RULE_TYPE_TOPIC,
    SME_NOT_MINE,
    STATUS_IN_PROGRESS,
    STATUS_OPEN,
    STATUS_RESOLVED,
    TICKET_STATUSES,
)
from tickets.db import get_db, init_db
from tickets.ingest import (
    advance_ingest_cursor,
    ensure_all_question_ids,
    get_ingest_cursor,
    ingest_date,
    ingest_date_range,
    ingest_previous_day,
    resolve_update_start,
    set_ticket_status,
)
from tickets.models import AssignmentRule, NotMineFeedback, Ticket, WhatsAppDraft
from tickets.routing import reassign_open_tickets
from tickets.session import clear_session, get_current_user, set_session
from tickets.agent.assign_learn import apply_not_mine_learnings, record_not_mine_feedback
from tickets.agent.criticality import assign_criticality_all
from tickets.agent.draft import draft_whatsapp_for_user, draft_whatsapp_for_users_with_notes
from tickets.agent.nudge import run_daily_sme_nudges
from tickets.agent.draft import tickets_with_notes_by_user

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="SME Ticket Resolution")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def _wants_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return "application/json" in accept


def visible_ticket_query(db: Session, user: User):
    return db.query(Ticket)


def apply_common_filters(
    query,
    user: User | None = None,
    *,
    programme: str = "",
    sme: str = "",
    start_date: str = "",
    end_date: str = "",
    q: str = "",
):
    del user
    if programme:
        query = query.filter(Ticket.programme == programme)
    if sme:
        query = query.filter(Ticket.sme_name == sme)
    start = parse_iso_date(start_date)
    end = parse_iso_date(end_date)
    if start:
        query = query.filter(Ticket.report_date >= start.isoformat())
    if end:
        query = query.filter(Ticket.report_date <= end.isoformat())
    if q.strip():
        like = f"%{q.strip()}%"
        query = query.filter(
            (Ticket.student_description.ilike(like))
            | (Ticket.org_assessment_title.ilike(like))
            | (Ticket.sme_name.ilike(like))
            | (Ticket.subject.ilike(like))
        )
    return query


def ticket_counts(
    db: Session,
    user: User,
    *,
    programme: str = "",
    sme: str = "",
    start_date: str = "",
    end_date: str = "",
    q: str = "",
) -> dict[str, int]:
    query = apply_common_filters(
        visible_ticket_query(db, user),
        user,
        programme=programme,
        sme=sme,
        start_date=start_date,
        end_date=end_date,
        q=q,
    )
    rows = query.with_entities(Ticket.status, func.count(Ticket.id)).group_by(Ticket.status).all()
    counts = {status: 0 for status in TICKET_STATUSES}
    for status, count in rows:
        counts[status] = count
    counts["all"] = sum(counts.values())
    return counts


def calendar_counts_by_date(db: Session, user: User) -> dict[str, dict[str, int]]:
    rows = (
        visible_ticket_query(db, user)
        .with_entities(Ticket.report_date, Ticket.status, func.count(Ticket.id))
        .group_by(Ticket.report_date, Ticket.status)
        .all()
    )
    result: dict[str, dict[str, int]] = {}
    for report_date, status, count in rows:
        if not report_date:
            continue
        bucket = result.setdefault(report_date, {"total": 0, "open": 0, "resolved": 0})
        bucket["total"] += count
        if status == "open" or status == "in_progress":
            bucket["open"] += count
        elif status == "resolved":
            bucket["resolved"] += count
    return result


def can_view_ticket(user: User, ticket: Ticket) -> bool:
    return user is not None and ticket is not None


def can_edit_ticket(user: User, ticket: Ticket) -> bool:
    if is_admin(user):
        return True
    return user.role == ROLE_SME and ticket.sme_name == user.display_name


def can_mark_not_mine(user: User, ticket: Ticket) -> bool:
    if is_admin(user) or user.role != ROLE_SME:
        return False
    return ticket.sme_name == user.display_name


def can_claim_ticket(user: User, ticket: Ticket) -> bool:
    if is_admin(user) or user.role != ROLE_SME:
        return False
    if ticket.sme_name == user.display_name:
        return False
    return ticket.status != STATUS_RESOLVED


def safe_return_to(value: str) -> str:
    cleaned = (value or "").strip()
    if cleaned.startswith("/") and not cleaned.startswith("//"):
        return cleaned
    return ""


def parse_return_to_filters(return_to: str) -> dict[str, str]:
    """Extract board filters from a return_to path like /?status=open&sme=…"""
    cleaned = safe_return_to(return_to)
    if not cleaned:
        return {}
    parsed = urlparse(cleaned)
    raw = parse_qs(parsed.query)
    return {key: (vals[0] if vals else "") for key, vals in raw.items()}


def related_question_tickets(
    db: Session,
    ticket: Ticket,
    *,
    return_to: str = "",
) -> list[Ticket]:
    """
    Same question_id, same SME, open/in_progress only, matching board filters.
    Returns [] when question_id is missing (caller keeps single-ticket flow).
    """
    qid = (ticket.question_id or "").strip()
    if not qid:
        return []

    filters = parse_return_to_filters(return_to)
    programme = filters.get("programme", "")
    start_date = filters.get("start_date", "")
    end_date = filters.get("end_date", "")
    q = filters.get("q", "")
    cal_year = filters.get("cal_year", "")
    cal_month = filters.get("cal_month", "")

    if not start_date and not end_date and cal_year and cal_month:
        try:
            year_i = int(cal_year)
            month_i = int(cal_month)
            if 1 <= month_i <= 12:
                start_date = date(year_i, month_i, 1).isoformat()
                end_date = date(year_i, month_i, monthrange(year_i, month_i)[1]).isoformat()
        except ValueError:
            pass

    query = (
        db.query(Ticket)
        .filter(
            Ticket.question_id == qid,
            Ticket.sme_name == ticket.sme_name,
            Ticket.status.in_([STATUS_OPEN, STATUS_IN_PROGRESS]),
        )
    )
    query = apply_common_filters(
        query,
        programme=programme,
        sme="",  # SME already locked to ticket.sme_name
        start_date=start_date,
        end_date=end_date,
        q=q,
    )
    # Always include the opened ticket even if it somehow falls outside date filters.
    siblings = query.order_by(Ticket.report_date.desc(), Ticket.id.desc()).limit(200).all()
    by_id = {t.id: t for t in siblings}
    if ticket.id not in by_id and ticket.status in (STATUS_OPEN, STATUS_IN_PROGRESS):
        by_id[ticket.id] = ticket
    ordered = sorted(
        by_id.values(),
        key=lambda t: (0 if t.id == ticket.id else 1, str(t.report_date or ""), -t.id),
    )
    return ordered


def shared_notes_for_group(tickets: list[Ticket], fallback: Ticket) -> str:
    """Prefer the longest non-empty notes in the group."""
    best = (fallback.notes or "").strip()
    for t in tickets:
        note = (t.notes or "").strip()
        if len(note) > len(best):
            best = note
    return best


def filter_query_string(
    *,
    status: str,
    programme: str,
    sme: str,
    start_date: str,
    end_date: str,
    q: str,
    cal_year: int | None = None,
    cal_month: int | None = None,
) -> str:
    parts = [
        f"status={status or 'all'}",
        f"programme={programme}",
        f"sme={sme}",
        f"start_date={start_date}",
        f"end_date={end_date}",
        f"q={q}",
    ]
    if cal_year and cal_month:
        parts.append(f"cal_year={cal_year}")
        parts.append(f"cal_month={cal_month}")
    return "&".join(parts)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if user:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": ""})


@app.post("/login")
def login_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    user = authenticate(db, username, password)
    if not user:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid username or password"},
            status_code=401,
        )
    response = RedirectResponse("/", status_code=303)
    set_session(response, user.id)
    return response


@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    clear_session(response)
    return response


def _month_update_range(year: int | None, month: int | None) -> tuple[date, date, int, int] | None:
    today = date.today()
    target_year = year or today.year
    target_month = month or today.month
    if target_month < 1 or target_month > 12:
        target_year, target_month = today.year, today.month
    start = date(target_year, target_month, 1)
    last_day = monthrange(target_year, target_month)[1]
    end = date(target_year, target_month, last_day)
    if end > today:
        end = today
    if start > today:
        return None
    return start, end, target_year, target_month


@app.get("/admin/update-reports/plan")
def admin_update_plan(
    request: Request,
    year: int | None = Query(None),
    month: int | None = Query(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not is_admin(user):
        return JSONResponse({"ok": False, "error": "Admin only"}, status_code=403)
    bounds = _month_update_range(year, month)
    if not bounds:
        return JSONResponse(
            {"ok": False, "error": "That month is in the future — nothing to update"}
        )
    month_start, end, target_year, target_month = bounds
    start, cursor = resolve_update_start(db, month_start, end)
    dates: list[str] = []
    day = start
    while day <= end:
        dates.append(day.isoformat())
        day += timedelta(days=1)
    resume_label = (cursor.last_through_creation or cursor.last_through_date or "").strip()
    return {
        "ok": True,
        "year": target_year,
        "month": target_month,
        "month_start": month_start.isoformat(),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "dates": dates,
        "total_days": len(dates),
        "resume_from": cursor.last_through_date or None,
        "resume_label": resume_label or None,
        "resumed": start > month_start,
    }


@app.post("/admin/update-reports/day")
async def admin_update_day(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not is_admin(user):
        return JSONResponse({"ok": False, "error": "Admin only"}, status_code=403)
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    day_raw = str((body or {}).get("date", "")).strip()
    try:
        target = date.fromisoformat(day_raw)
    except ValueError:
        return JSONResponse({"ok": False, "error": "Invalid date"}, status_code=400)
    try:
        result = ingest_date(db, target, enrich=True)
        cursor = advance_ingest_cursor(db, target)
        return {
            "ok": True,
            "date": target.isoformat(),
            "created": result.get("created", 0),
            "skipped": result.get("skipped", 0),
            "total_rows": result.get("total_rows", 0),
            "cursor_through": cursor.last_through_date,
            "cursor_creation": cursor.last_through_creation or None,
        }
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            {
                "ok": False,
                "date": target.isoformat(),
                "error": str(exc)[:240],
            },
            status_code=500,
        )


@app.post("/admin/update-reports/finalize")
def admin_update_finalize(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not is_admin(user):
        return JSONResponse({"ok": False, "error": "Admin only"}, status_code=403)
    try:
        crit = assign_criticality_all(db, only_missing=True)
        cursor = get_ingest_cursor(db)
        return {
            "ok": True,
            "criticality_updated": crit.get("updated", 0),
            "cursor_through": cursor.last_through_date or None,
            "cursor_creation": cursor.last_through_creation or None,
        }
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)[:240]}, status_code=500)


@app.post("/admin/update-reports")
def admin_update_reports(
    request: Request,
    year: int | None = Form(None),
    month: int | None = Form(None),
    db: Session = Depends(get_db),
):
    """Fallback full-month update (non-JS). Prefer day-by-day UI flow."""
    user = get_current_user(request, db)
    if not user or not is_admin(user):
        return RedirectResponse("/", status_code=303)

    bounds = _month_update_range(year, month)
    if not bounds:
        today = date.today()
        return RedirectResponse(
            f"/?msg={quote_plus('That month is in the future — nothing to update')}"
            f"&cal_year={year or today.year}&cal_month={month or today.month}",
            status_code=303,
        )
    month_start, end, target_year, target_month = bounds
    start, cursor = resolve_update_start(db, month_start, end)

    try:
        result = ingest_date_range(db, start, end, enrich=True)
        advance_ingest_cursor(db, end)
        crit = assign_criticality_all(db, only_missing=True)
        resume_note = ""
        if start > month_start and (cursor.last_through_creation or cursor.last_through_date):
            resume_note = (
                f" (resumed from {cursor.last_through_creation or cursor.last_through_date})"
            )
        msg = (
            f"Updated {result.get('start_date', start.isoformat())} → "
            f"{result.get('end_date', end.isoformat())}{resume_note}: "
            f"created {result.get('created', 0)}, "
            f"skipped {result.get('skipped', 0)}, "
            f"criticality {crit.get('updated', 0)}"
        )
    except Exception as exc:  # noqa: BLE001
        msg = f"Update failed: {str(exc)[:160]}"

    return RedirectResponse(
        f"/?msg={quote_plus(msg)}&cal_year={target_year}&cal_month={target_month}",
        status_code=303,
    )


@app.get("/", response_class=HTMLResponse)
def ticket_board(
    request: Request,
    status: str = Query("open"),
    programme: str = Query(""),
    sme: str = Query(""),
    start_date: str = Query(""),
    end_date: str = Query(""),
    report_date: str = Query(""),  # legacy single-day link from calendar
    q: str = Query(""),
    cal_year: int | None = Query(None),
    cal_month: int | None = Query(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()

    # Calendar day click sets a single day via report_date.
    if report_date and not start_date and not end_date:
        start_date = report_date
        end_date = report_date

    query = apply_common_filters(
        visible_ticket_query(db, user),
        user,
        programme=programme,
        sme=sme,
        start_date=start_date,
        end_date=end_date,
        q=q,
    )
    if status and status != "all":
        query = query.filter(Ticket.status == status)

    tickets = query.order_by(Ticket.report_date.desc(), Ticket.id.desc()).limit(500).all()

    today = date.today()
    year = cal_year or today.year
    month = cal_month or today.month
    if month < 1 or month > 12:
        year, month = today.year, today.month

    prev_year, prev_month = shift_month(year, month, -1)
    next_year, next_month = shift_month(year, month, 1)
    qs = filter_query_string(
        status=status or "all",
        programme=programme,
        sme=sme,
        start_date=start_date,
        end_date=end_date,
        q=q,
    )

    return templates.TemplateResponse(
        request,
        "tickets.html",
        {
            "user": user,
            "is_admin": is_admin(user),
            "tickets": tickets,
            "counts": ticket_counts(
                db,
                user,
                programme=programme,
                sme=sme,
                start_date=start_date,
                end_date=end_date,
                q=q,
            ),
            "filters": {
                "status": status or "all",
                "programme": programme,
                "sme": sme,
                "start_date": start_date,
                "end_date": end_date,
                "q": q,
            },
            "sme_names": list_admin_sme_filters(db),
            "assignable_smes": list_assignable_smes(db),
            "not_mine_label": SME_NOT_MINE,
            "current_sme_name": user.display_name if user.role == ROLE_SME else "",
            "auto_refresh_seconds": 0,
            "message": request.query_params.get("msg", ""),
            "statuses": TICKET_STATUSES,
            "grit_subjects": GRIT_SUBJECTS,
            "programme_grit": PROGRAMME_GRIT,
            "programme_niat": PROGRAMME_NIAT_SKILL,
            "programme_intensive": PROGRAMME_INTENSIVE_OFFLINE,
            "calendar": {
                "title": month_title(year, month),
                "days": build_calendar_days(year, month, calendar_counts_by_date(db, user)),
                "prev_href": f"/?{qs}&cal_year={prev_year}&cal_month={prev_month}",
                "next_href": f"/?{qs}&cal_year={next_year}&cal_month={next_month}",
                "year": year,
                "month": month,
            },
        },
    )


def ticket_detail_url(ticket_id: int, return_to: str = "") -> str:
    base = f"/tickets/{ticket_id}"
    cleaned = safe_return_to(return_to)
    if cleaned:
        return f"{base}?return_to={quote_plus(cleaned)}"
    return base


@app.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_detail(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()

    ticket = db.get(Ticket, ticket_id)
    if not ticket or not can_view_ticket(user, ticket):
        return RedirectResponse("/", status_code=303)

    return_to = safe_return_to(request.query_params.get("return_to", ""))
    related = related_question_tickets(db, ticket, return_to=return_to)
    question_group = bool((ticket.question_id or "").strip()) and len(related) >= 1
    # Single-ticket flow when no question_id; with qid always use group mode (at least self).
    if not (ticket.question_id or "").strip():
        related = [ticket]
        question_group = False
    elif ticket not in related and ticket.id not in {t.id for t in related}:
        related = [ticket] + related

    shared_notes = shared_notes_for_group(related, ticket) if question_group else (ticket.notes or "")

    return templates.TemplateResponse(
        request,
        "ticket_detail.html",
        {
            "user": user,
            "is_admin": is_admin(user),
            "ticket": ticket,
            "related_tickets": related if question_group else [],
            "question_group": question_group,
            "shared_notes": shared_notes,
            "can_mark_not_mine": can_mark_not_mine(user, ticket),
            "can_claim": can_claim_ticket(user, ticket),
            "can_edit": can_edit_ticket(user, ticket),
            "error": request.query_params.get("err", ""),
            "message": request.query_params.get("msg", ""),
            "return_to": return_to,
            "tag_list": [t.strip() for t in (ticket.question_tags or "").split(",") if t.strip()],
            "statuses": TICKET_STATUSES,
            "assignable_smes": list_assignable_smes(db)
            + ([SME_NOT_MINE] if is_admin(user) else []),
            "auto_refresh_seconds": 0,
        },
    )


@app.get("/api/tickets/statuses")
def api_ticket_statuses(
    request: Request,
    ids: str = Query(""),
    db: Session = Depends(get_db),
):
    """Lightweight status lookup for board sync after resolving in another tab."""
    user = get_current_user(request, db)
    if not user:
        return JSONResponse({"ok": False, "error": "login required"}, status_code=401)
    raw_ids = [part.strip() for part in (ids or "").split(",") if part.strip()]
    ticket_ids: list[int] = []
    for part in raw_ids[:200]:
        try:
            ticket_ids.append(int(part))
        except ValueError:
            continue
    if not ticket_ids:
        return {"ok": True, "tickets": []}
    rows = (
        db.query(Ticket.id, Ticket.status, Ticket.report_date)
        .filter(Ticket.id.in_(ticket_ids))
        .all()
    )
    return {
        "ok": True,
        "tickets": [
            {
                "id": row.id,
                "status": row.status,
                "report_date": row.report_date or "",
            }
            for row in rows
        ],
    }


@app.post("/tickets/{ticket_id}/update")
def update_ticket(
    ticket_id: int,
    request: Request,
    status: str = Form(...),
    sme_name: str = Form(""),
    notes: str = Form(""),
    return_to: str = Form(""),
    apply_question_group: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "login required"}, status_code=401)
        return _login_redirect()

    ticket = db.get(Ticket, ticket_id)
    if not ticket or not can_edit_ticket(user, ticket):
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "not allowed"}, status_code=403)
        return RedirectResponse("/", status_code=303)

    prev_status = ticket.status
    notes_clean = notes.strip()
    use_group = apply_question_group == "1" and bool((ticket.question_id or "").strip())
    group = related_question_tickets(db, ticket, return_to=return_to) if use_group else [ticket]
    if use_group and ticket.id not in {t.id for t in group}:
        group = [ticket] + group
    if not group:
        group = [ticket]

    if is_admin(user):
        cleaned = sme_name.strip() or "Unassigned"
        if cleaned in list_assignable_smes(db) or cleaned == SME_NOT_MINE:
            ticket.sme_name = cleaned
        new_status = status if status in TICKET_STATUSES else STATUS_OPEN
    else:
        if status in TICKET_STATUSES:
            new_status = status
        else:
            new_status = ticket.status

    editable = [item for item in group if item.id == ticket.id or can_edit_ticket(user, item)]
    for item in editable:
        item.notes = notes_clean
        if new_status == STATUS_RESOLVED:
            set_ticket_status(db, item, STATUS_RESOLVED)
        elif item.id == ticket.id:
            set_ticket_status(db, item, new_status)
        else:
            db.add(item)
    db.commit()

    ticket_ids = [item.id for item in editable]
    if _wants_json(request):
        redirect = ""
        if new_status == STATUS_RESOLVED and use_group and len(editable) > 1:
            msg = quote_plus(f"Resolved {len(editable)} tickets for this question")
            target = safe_return_to(return_to) or "/"
            sep = "&" if "?" in target else "?"
            redirect = f"{target}{sep}msg={msg}"
        else:
            redirect = ticket_detail_url(ticket_id, return_to)
        return JSONResponse(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "ticket_ids": ticket_ids,
                "status": new_status,
                "prev_status": prev_status,
                "report_date": ticket.report_date or "",
                "redirect": redirect,
            }
        )

    if new_status == STATUS_RESOLVED and use_group and len(editable) > 1:
        msg = quote_plus(f"Resolved {len(editable)} tickets for this question")
        target = safe_return_to(return_to) or "/"
        sep = "&" if "?" in target else "?"
        return RedirectResponse(f"{target}{sep}msg={msg}", status_code=303)

    return RedirectResponse(ticket_detail_url(ticket_id, return_to), status_code=303)


@app.post("/tickets/{ticket_id}/quick-resolve")
def quick_resolve(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "login required"}, status_code=401)
        return _login_redirect()
    ticket = db.get(Ticket, ticket_id)
    if not ticket or not can_edit_ticket(user, ticket):
        if _wants_json(request):
            return JSONResponse({"ok": False, "error": "not allowed"}, status_code=403)
        return RedirectResponse(request.headers.get("referer", "/"), status_code=303)

    prev_status = ticket.status
    set_ticket_status(db, ticket, STATUS_RESOLVED)
    if _wants_json(request):
        return JSONResponse(
            {
                "ok": True,
                "ticket_id": ticket_id,
                "status": STATUS_RESOLVED,
                "prev_status": prev_status,
                "report_date": ticket.report_date or "",
            }
        )
    return RedirectResponse(request.headers.get("referer", "/"), status_code=303)


@app.post("/tickets/{ticket_id}/quick-open")
def quick_open(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()
    ticket = db.get(Ticket, ticket_id)
    if ticket and can_edit_ticket(user, ticket) and is_admin(user):
        set_ticket_status(db, ticket, STATUS_OPEN)
    return RedirectResponse(request.headers.get("referer", "/"), status_code=303)


@app.post("/tickets/{ticket_id}/assign")
def assign_ticket(
    ticket_id: int,
    request: Request,
    sme_name: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()
    if not is_admin(user):
        return RedirectResponse("/", status_code=303)

    ticket = db.get(Ticket, ticket_id)
    if ticket and sme_name.strip() in list_assignable_smes(db):
        ticket.sme_name = sme_name.strip()
        db.commit()
    return RedirectResponse(request.headers.get("referer", "/"), status_code=303)


@app.get("/whatsapp", response_class=HTMLResponse)
def whatsapp_board(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()

    drafts = db.query(WhatsAppDraft).order_by(WhatsAppDraft.updated_at.desc()).all()
    pending_users = sorted(tickets_with_notes_by_user(db).keys())
    drafted_ids = {d.user_id for d in drafts}
    return templates.TemplateResponse(
        request,
        "whatsapp.html",
        {
            "user": user,
            "is_admin": is_admin(user),
            "drafts": drafts,
            "pending_count": len(pending_users),
            "missing_draft_count": len([u for u in pending_users if u not in drafted_ids]),
            "auto_refresh_seconds": 0,
        },
    )


@app.post("/whatsapp/generate")
def whatsapp_generate(
    request: Request,
    user_id: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()
    try:
        if user_id.strip():
            draft_whatsapp_for_user(db, user_id.strip(), use_llm=True)
        else:
            draft_whatsapp_for_users_with_notes(db, use_llm=True, limit=50)
    except Exception as exc:  # noqa: BLE001
        return templates.TemplateResponse(
            request,
            "whatsapp.html",
            {
                "user": user,
                "is_admin": is_admin(user),
                "drafts": db.query(WhatsAppDraft).order_by(WhatsAppDraft.updated_at.desc()).all(),
                "pending_count": 0,
                "missing_draft_count": 0,
                "error": str(exc),
            },
            status_code=400,
        )
    return RedirectResponse("/whatsapp", status_code=303)


@app.post("/whatsapp/{draft_id}/save")
def whatsapp_save(
    draft_id: int,
    request: Request,
    message_text: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()
    draft = db.get(WhatsAppDraft, draft_id)
    if draft:
        draft.message_text = message_text.strip()
        db.commit()
    return RedirectResponse("/whatsapp", status_code=303)


@app.post("/tickets/{ticket_id}/not-mine")
def mark_not_mine(
    ticket_id: int,
    request: Request,
    reason: str = Form(...),
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()
    ticket = db.get(Ticket, ticket_id)
    reason = reason.strip()
    back = safe_return_to(return_to) or request.headers.get("referer", "/")
    if not ticket or not can_mark_not_mine(user, ticket):
        return RedirectResponse(back, status_code=303)
    if len(reason) < 8:
        detail = ticket_detail_url(ticket_id, return_to)
        sep = "&" if "?" in detail else "?"
        return RedirectResponse(
            f"{detail}{sep}err="
            + quote_plus("Please explain why this ticket is not yours (min 8 chars)"),
            status_code=303,
        )
    record_not_mine_feedback(db, ticket, from_sme=user.display_name, reason=reason)
    ticket.sme_name = SME_NOT_MINE
    if ticket.status == STATUS_RESOLVED:
        ticket.status = STATUS_OPEN
        ticket.resolved_at = None
    db.commit()
    return RedirectResponse(safe_return_to(return_to) or "/", status_code=303)


@app.post("/tickets/{ticket_id}/claim")
def claim_ticket(
    ticket_id: int,
    request: Request,
    return_to: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()
    ticket = db.get(Ticket, ticket_id)
    if not ticket or not can_claim_ticket(user, ticket):
        return RedirectResponse(
            safe_return_to(return_to) or request.headers.get("referer", "/"),
            status_code=303,
        )
    ticket.sme_name = user.display_name
    db.commit()
    return RedirectResponse(ticket_detail_url(ticket_id, return_to), status_code=303)


@app.get("/assignments", response_class=HTMLResponse)
def assignments_page(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()
    if not is_admin(user):
        return RedirectResponse("/", status_code=303)

    not_mine = (
        db.query(Ticket)
        .filter(Ticket.sme_name == SME_NOT_MINE)
        .order_by(Ticket.id.desc())
        .limit(200)
        .all()
    )
    feedback_by_ticket: dict[int, NotMineFeedback] = {}
    if not_mine:
        ticket_ids = [t.id for t in not_mine]
        for fb in (
            db.query(NotMineFeedback)
            .filter(NotMineFeedback.ticket_id.in_(ticket_ids))
            .order_by(NotMineFeedback.id.desc())
            .all()
        ):
            if fb.ticket_id not in feedback_by_ticket:
                feedback_by_ticket[fb.ticket_id] = fb
    pending_feedback = (
        db.query(NotMineFeedback).filter(NotMineFeedback.applied.is_(False)).count()
    )
    topic_rules = (
        db.query(AssignmentRule)
        .filter(AssignmentRule.rule_type == RULE_TYPE_TOPIC)
        .order_by(AssignmentRule.id.desc())
        .all()
    )
    title_rules = (
        db.query(AssignmentRule)
        .filter(AssignmentRule.rule_type == RULE_TYPE_ASSESSMENT)
        .order_by(AssignmentRule.id.desc())
        .all()
    )
    return templates.TemplateResponse(
        request,
        "assignments.html",
        {
            "user": user,
            "is_admin": True,
            "not_mine": not_mine,
            "feedback_by_ticket": feedback_by_ticket,
            "pending_feedback": pending_feedback,
            "topic_rules": topic_rules,
            "title_rules": title_rules,
            "assignable_smes": list_assignable_smes(db),
            "sme_people": [
                u
                for u in db.query(User)
                .filter(User.role == ROLE_SME)
                .order_by(User.display_name.asc())
                .all()
            ],
            "rule_type_topic": RULE_TYPE_TOPIC,
            "rule_type_assessment": RULE_TYPE_ASSESSMENT,
            "message": request.query_params.get("msg", ""),
            "auto_refresh_seconds": 0,
        },
    )


@app.post("/assignments/rules/add")
def add_assignment_rule(
    request: Request,
    rule_type: str = Form(...),
    marker: str = Form(...),
    sme_name: str = Form(...),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not is_admin(user):
        return RedirectResponse("/", status_code=303)
    if rule_type not in (RULE_TYPE_TOPIC, RULE_TYPE_ASSESSMENT):
        return RedirectResponse("/assignments", status_code=303)
    if sme_name not in list_assignable_smes(db):
        return RedirectResponse("/assignments", status_code=303)
    marker = marker.strip()
    if not marker:
        return RedirectResponse("/assignments", status_code=303)
    db.add(
        AssignmentRule(
            rule_type=rule_type,
            marker=marker,
            sme_name=sme_name,
            priority=100,
            active=True,
        )
    )
    db.commit()
    return RedirectResponse("/assignments?msg=Rule+added", status_code=303)


@app.post("/assignments/people/add")
def add_assignment_person(
    request: Request,
    display_name: str = Form(...),
    username: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user or not is_admin(user):
        return RedirectResponse("/", status_code=303)
    created, err = create_sme_user(
        db,
        display_name=display_name,
        username=username,
        password=password,
    )
    if err:
        return RedirectResponse(f"/assignments?msg={quote_plus(err)}", status_code=303)
    msg = (
        f"Added {created.display_name} "
        f"(login: {created.username}). They appear in SME dropdowns now."
    )
    return RedirectResponse(f"/assignments?msg={quote_plus(msg)}", status_code=303)


@app.post("/assignments/rules/{rule_id}/delete")
def delete_assignment_rule(
    rule_id: int, request: Request, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user or not is_admin(user):
        return RedirectResponse("/", status_code=303)
    rule = db.get(AssignmentRule, rule_id)
    if rule:
        db.delete(rule)
        db.commit()
    return RedirectResponse("/assignments?msg=Rule+deleted", status_code=303)


@app.post("/assignments/rules/{rule_id}/toggle")
def toggle_assignment_rule(
    rule_id: int, request: Request, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user or not is_admin(user):
        return RedirectResponse("/", status_code=303)
    rule = db.get(AssignmentRule, rule_id)
    if rule:
        rule.active = not rule.active
        db.commit()
    return RedirectResponse("/assignments", status_code=303)


@app.post("/assignments/reapply")
def reapply_assignments(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not is_admin(user):
        return RedirectResponse("/", status_code=303)
    updated = reassign_open_tickets(db, skip_not_mine=True)
    return RedirectResponse(
        f"/assignments?msg=Reassigned+{updated}+tickets+(Not+mine+left+unchanged)",
        status_code=303,
    )


@app.post("/assignments/apply-learnings")
def apply_learnings(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user or not is_admin(user):
        return RedirectResponse("/", status_code=303)
    result = apply_not_mine_learnings(db)
    return RedirectResponse(
        "/assignments?msg="
        f"Applied+{result['feedback_applied']}+feedback+"
        f"(+{result['rules_added']}+rules,+{result['not_mine_cleared']}+Not+mine+cleared)",
        status_code=303,
    )


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/agent/nudge")
def api_agent_nudge(
    request: Request,
    dry_run: bool = Query(False),
    db: Session = Depends(get_db),
):
    _require_ingest_token(request)
    return {"results": run_daily_sme_nudges(db, dry_run=dry_run)}


@app.post("/api/ingest/previous-day")
def api_ingest_previous_day(
    request: Request,
    enrich: bool = Query(True),
    db: Session = Depends(get_db),
):
    _require_ingest_token(request)
    return ingest_previous_day(db, enrich=enrich)


@app.post("/api/ingest/repair-question-ids")
def api_repair_question_ids(
    request: Request,
    enrich: bool = Query(True),
    db: Session = Depends(get_db),
):
    """Backfill question_id (and type/text/tags) for every ticket missing it."""
    _require_ingest_token(request)
    return ensure_all_question_ids(db, enrich=enrich)


@app.post("/api/ingest/{report_date}")
def api_ingest_date(
    report_date: str,
    request: Request,
    enrich: bool = Query(True),
    db: Session = Depends(get_db),
):
    _require_ingest_token(request)
    target = date.fromisoformat(report_date)
    result = ingest_date(db, target, enrich=enrich)
    result["report_date"] = target.isoformat()
    return result


def _require_ingest_token(request: Request) -> None:
    expected = os.getenv("INGEST_TOKEN", "").strip()
    hosted = bool(os.getenv("RAILWAY_ENVIRONMENT", "").strip()) or os.getenv(
        "RENDER", ""
    ).strip().lower() == "true"
    if not expected:
        if hosted:
            from fastapi import HTTPException

            raise HTTPException(status_code=503, detail="INGEST_TOKEN not configured")
        return
    provided = request.headers.get("X-Ingest-Token", "")
    if provided != expected:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid ingest token")

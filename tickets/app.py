"""Ticket resolution web app."""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import Session

from tickets.auth import User, authenticate, is_admin
from tickets.calendar_view import (
    build_calendar_days,
    month_title,
    parse_iso_date,
    shift_month,
)
from tickets.config import (
    ASSIGNABLE_SMES,
    GRIT_SUBJECTS,
    PROGRAMME_GRIT,
    PROGRAMME_NIAT_SKILL,
    STATUS_OPEN,
    STATUS_RESOLVED,
    TICKET_STATUSES,
)
from tickets.db import get_db, init_db
from tickets.ingest import ingest_date, ingest_previous_day, set_ticket_status
from tickets.models import Ticket
from tickets.session import clear_session, get_current_user, set_session

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="SME Ticket Resolution")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def _login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def visible_ticket_query(db: Session, user: User):
    query = db.query(Ticket)
    if not is_admin(user):
        query = query.filter(Ticket.sme_name == user.display_name)
    return query


def apply_common_filters(
    query,
    user: User,
    *,
    programme: str = "",
    sme: str = "",
    start_date: str = "",
    end_date: str = "",
    q: str = "",
):
    if programme:
        query = query.filter(Ticket.programme == programme)
    if sme and is_admin(user):
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


def can_edit_ticket(user: User, ticket: Ticket) -> bool:
    if is_admin(user):
        return True
    return ticket.sme_name == user.display_name


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
            "sme_names": list(ASSIGNABLE_SMES),
            "statuses": TICKET_STATUSES,
            "grit_subjects": GRIT_SUBJECTS,
            "programme_grit": PROGRAMME_GRIT,
            "programme_niat": PROGRAMME_NIAT_SKILL,
            "assignable_smes": ASSIGNABLE_SMES,
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


@app.get("/tickets/{ticket_id}", response_class=HTMLResponse)
def ticket_detail(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()

    ticket = db.get(Ticket, ticket_id)
    if not ticket or not can_edit_ticket(user, ticket):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        request,
        "ticket_detail.html",
        {
            "user": user,
            "is_admin": is_admin(user),
            "ticket": ticket,
            "statuses": TICKET_STATUSES,
            "assignable_smes": ASSIGNABLE_SMES,
        },
    )


@app.post("/tickets/{ticket_id}/update")
def update_ticket(
    ticket_id: int,
    request: Request,
    status: str = Form(...),
    sme_name: str = Form(""),
    notes: str = Form(""),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()

    ticket = db.get(Ticket, ticket_id)
    if not ticket or not can_edit_ticket(user, ticket):
        return RedirectResponse("/", status_code=303)

    ticket.notes = notes.strip()
    if is_admin(user):
        cleaned = sme_name.strip() or "Unassigned"
        if cleaned in ASSIGNABLE_SMES:
            ticket.sme_name = cleaned
        new_status = status if status in TICKET_STATUSES else STATUS_OPEN
    else:
        if status in TICKET_STATUSES:
            new_status = status
        else:
            new_status = ticket.status

    set_ticket_status(db, ticket, new_status)
    return RedirectResponse(f"/tickets/{ticket_id}", status_code=303)


@app.post("/tickets/{ticket_id}/quick-resolve")
def quick_resolve(ticket_id: int, request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        return _login_redirect()
    ticket = db.get(Ticket, ticket_id)
    if ticket and can_edit_ticket(user, ticket):
        set_ticket_status(db, ticket, STATUS_RESOLVED)
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
    if ticket and sme_name.strip() in ASSIGNABLE_SMES:
        ticket.sme_name = sme_name.strip()
        db.commit()
    return RedirectResponse(request.headers.get("referer", "/"), status_code=303)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/api/ingest/previous-day")
def api_ingest_previous_day(
    request: Request,
    enrich: bool = Query(False),
    db: Session = Depends(get_db),
):
    _require_ingest_token(request)
    return ingest_previous_day(db, enrich=enrich)


@app.post("/api/ingest/{report_date}")
def api_ingest_date(
    report_date: str,
    request: Request,
    enrich: bool = Query(False),
    db: Session = Depends(get_db),
):
    _require_ingest_token(request)
    target = date.fromisoformat(report_date)
    result = ingest_date(db, target, enrich=enrich)
    result["report_date"] = target.isoformat()
    return result


def _require_ingest_token(request: Request) -> None:
    expected = os.getenv("INGEST_TOKEN", "").strip()
    if not expected:
        return
    provided = request.headers.get("X-Ingest-Token", "")
    if provided != expected:
        from fastapi import HTTPException

        raise HTTPException(status_code=401, detail="Invalid ingest token")

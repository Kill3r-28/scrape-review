"""Daily email nudge: open tickets this calendar month per SME."""

from __future__ import annotations

import os
import smtplib
from datetime import datetime
from email.message import EmailMessage
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from tickets.config import (
    ASSIGNABLE_SMES,
    SME_EMAILS,
    SME_UNASSIGNED,
    STATUS_OPEN,
    STATUS_IN_PROGRESS,
)
from tickets.models import NudgeLog, Ticket

IST = ZoneInfo("Asia/Kolkata")


def month_key(now: datetime | None = None) -> str:
    now = now or datetime.now(IST)
    return now.strftime("%Y-%m")


def open_ticket_count_this_month(db: Session, sme_name: str, key: str | None = None) -> int:
    key = key or month_key()
    return (
        db.query(Ticket)
        .filter(Ticket.sme_name == sme_name)
        .filter(Ticket.status.in_([STATUS_OPEN, STATUS_IN_PROGRESS]))
        .filter(Ticket.report_date.startswith(key))
        .count()
    )


def build_nudge_body(sme_name: str, open_count: int, key: str) -> str:
    return (
        f"Hi {sme_name},\n\n"
        f"You have {open_count} open ticket(s) for {key} "
        f"(status open or in progress).\n\n"
        f"Please log in to the SME Ticket dashboard and resolve them.\n\n"
        f"— Ticket Agent\n"
    )


def send_email(to_addr: str, subject: str, body: str) -> tuple[bool, str]:
    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587") or "587")
    user = os.getenv("SMTP_USER", "").strip()
    password = os.getenv("SMTP_PASSWORD", "").strip()
    from_addr = os.getenv("SMTP_FROM", "").strip() or user
    if not host or not to_addr or not from_addr:
        return False, "SMTP not configured or missing recipient"
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg.set_content(body)
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True, "sent"
    except Exception as exc:  # noqa: BLE001 — surface in nudge log
        return False, str(exc)


def run_daily_sme_nudges(db: Session, *, dry_run: bool = False) -> list[dict]:
    key = month_key()
    results: list[dict] = []
    for sme_name in ASSIGNABLE_SMES:
        if sme_name == SME_UNASSIGNED:
            continue
        count = open_ticket_count_this_month(db, sme_name, key)
        email = (SME_EMAILS.get(sme_name) or "").strip()
        body = build_nudge_body(sme_name, count, key)
        subject = f"[SME Tickets] {count} open this month ({key})"

        if count == 0:
            sent = "skipped"
            detail = "no open tickets this month"
        elif dry_run:
            sent = "dry_run"
            detail = f"would email {email or '(no address)'}: {body[:120]}"
        elif not email:
            sent = "skipped"
            detail = "no email configured in SME_EMAILS"
        else:
            ok, detail = send_email(email, subject, body)
            sent = "sent" if ok else "failed"

        db.add(
            NudgeLog(
                sme_name=sme_name,
                email=email,
                open_count=count,
                month_key=key,
                sent=sent,
                detail=detail,
            )
        )
        results.append(
            {
                "sme_name": sme_name,
                "email": email,
                "open_count": count,
                "month_key": key,
                "sent": sent,
                "detail": detail,
            }
        )
    db.commit()
    return results

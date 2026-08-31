"""Draft WhatsApp messages per student user_id from SME notes (LLM)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import requests
from sqlalchemy.orm import Session

from tickets.config import DEFAULT_DRAFT_MODEL
from tickets.models import Ticket, WhatsAppDraft

BASE_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = BASE_DIR / ".env"
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def load_dotenv(path: Path = ENV_PATH) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def tickets_with_notes_by_user(db: Session, user_id: str | None = None) -> dict[str, list[Ticket]]:
    query = db.query(Ticket).filter(Ticket.notes != "").filter(Ticket.user_id != "")
    if user_id:
        query = query.filter(Ticket.user_id == user_id)
    grouped: dict[str, list[Ticket]] = {}
    for ticket in query.order_by(Ticket.id.asc()).all():
        grouped.setdefault(ticket.user_id, []).append(ticket)
    return grouped


def _fallback_message(user_id: str, tickets: list[Ticket]) -> str:
    lines = [
        f"Hi,",
        "",
        f"Update on your assessment report(s) (user: {user_id[:8]}…):",
        "",
    ]
    for t in tickets:
        lines.append(f"• Ticket #{t.id}: {t.notes.strip()}")
    lines.extend(["", "Thank you,", "Support Team"])
    return "\n".join(lines)


def _call_openrouter(prompt: str) -> str:
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY missing")
    model = os.getenv("OPENROUTER_MODEL", DEFAULT_DRAFT_MODEL).strip() or DEFAULT_DRAFT_MODEL
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": os.getenv("OPENROUTER_REFERER", "http://localhost"),
        "X-Title": os.getenv("OPENROUTER_TITLE", "sme-ticket-agent"),
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You draft short WhatsApp messages to students about their "
                    "assessment report tickets. Use only the SME notes provided. "
                    "Be clear, polite, and concrete. Do not invent facts. "
                    "Return only the message text, no JSON or markdown fences."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
    }
    response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=90)
    response.raise_for_status()
    data = response.json()
    return str(data["choices"][0]["message"]["content"]).strip()


def build_draft_prompt(user_id: str, tickets: list[Ticket]) -> str:
    items = []
    for t in tickets:
        items.append(
            {
                "ticket_id": t.id,
                "assessment": t.org_assessment_title,
                "student_claim": t.student_description,
                "sme_notes": t.notes,
                "status": t.status,
            }
        )
    return (
        "Draft one WhatsApp message for this student covering all listed tickets. "
        "Combine related points. Keep it under 400 words.\n\n"
        f"user_id: {user_id}\n"
        f"tickets:\n{json.dumps(items, ensure_ascii=False, indent=2)}"
    )


def draft_whatsapp_for_user(
    db: Session,
    user_id: str,
    *,
    use_llm: bool = True,
) -> WhatsAppDraft:
    grouped = tickets_with_notes_by_user(db, user_id)
    tickets = grouped.get(user_id, [])
    if not tickets:
        raise ValueError(f"No tickets with notes for user_id={user_id}")

    notes_blob = "\n---\n".join(
        f"#{t.id} [{t.status}] {t.notes.strip()}" for t in tickets
    )
    ticket_ids = ",".join(str(t.id) for t in tickets)

    if use_llm:
        try:
            message = _call_openrouter(build_draft_prompt(user_id, tickets))
        except Exception:
            message = _fallback_message(user_id, tickets)
    else:
        message = _fallback_message(user_id, tickets)

    existing = db.query(WhatsAppDraft).filter(WhatsAppDraft.user_id == user_id).one_or_none()
    if existing:
        existing.message_text = message
        existing.ticket_ids = ticket_ids
        existing.source_notes = notes_blob
        draft = existing
    else:
        draft = WhatsAppDraft(
            user_id=user_id,
            message_text=message,
            ticket_ids=ticket_ids,
            source_notes=notes_blob,
        )
        db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def draft_whatsapp_for_users_with_notes(
    db: Session,
    *,
    use_llm: bool = True,
    limit: int | None = None,
) -> list[WhatsAppDraft]:
    grouped = tickets_with_notes_by_user(db)
    user_ids = list(grouped.keys())
    if limit is not None:
        user_ids = user_ids[:limit]
    drafts: list[WhatsAppDraft] = []
    for uid in user_ids:
        drafts.append(draft_whatsapp_for_user(db, uid, use_llm=use_llm))
    return drafts

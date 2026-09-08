"""Learn assignment rules from SME 'Not mine' feedback."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from tickets.config import (
    ASSIGNABLE_SMES,
    RULE_TYPE_ASSESSMENT,
    RULE_TYPE_TOPIC,
    SME_NOT_MINE,
    SME_UNASSIGNED,
    TOPIC_SME_RULES,
)
from tickets.models import AssignmentRule, NotMineFeedback, Ticket
from tickets.routing import assign_sme, reassign_open_tickets, topic_tags

LEARNING_POINTS_FILE = Path(__file__).resolve().parent.parent.parent / "learning_points.txt"


def append_learning_point(ticket: Ticket, *, from_sme: str, reason: str) -> None:
    """Append SME feedback to learning_points.txt for manual rule updates."""
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    block = (
        f"{stamp} | ticket #{ticket.id} | from: {from_sme} | was: {ticket.sme_name}\n"
        f"Assessment: {ticket.org_assessment_title or '—'}\n"
        f"Tags: {ticket.question_tags or '—'}\n"
        f"Reason: {reason.strip()}\n"
        "---\n"
    )
    with LEARNING_POINTS_FILE.open("a", encoding="utf-8") as fh:
        fh.write(block)



def _sme_name_tokens() -> dict[str, str]:
    tokens: dict[str, str] = {}
    for name in ASSIGNABLE_SMES:
        if name in (SME_UNASSIGNED, SME_NOT_MINE):
            continue
        first = name.split()[0].upper()
        tokens[first] = name
        tokens[name.upper()] = name
    return tokens


def infer_sme_from_reason(
    reason: str,
    question_tags: str = "",
    org_assessment_title: str = "",
) -> str | None:
    """Best-effort SME guess from free-text reason + ticket context."""
    reason_upper = (reason or "").upper()
    context_upper = f"{question_tags} {org_assessment_title}".upper()

    for token, sme_name in _sme_name_tokens().items():
        if token in reason_upper:
            return sme_name

    blob = f"{reason_upper} {context_upper}"
    for sme_name, markers in TOPIC_SME_RULES:
        for marker in markers:
            if marker.upper() in blob:
                return sme_name

    keyword_map = {
        "REACT": "Viharika",
        "HTML": "Viharika",
        "CSS": "Viharika",
        "FRONTEND": "Viharika",
        "NODE": "Viharika",
        "WEB": "Viharika",
        "VERBAL": "Mariyam",
        "QUANT": "Poojitha Pachava",
        "LOGICAL": "Poojitha Pachava",
        "APTITUDE": "Poojitha Pachava",
        "DSA": "Varsha",
        "CODING": "Varsha",
        "SQL": "Varsha",
        "PYTHON": "Varsha",
        "JAVA": "Varsha",
        "CS FUNDAMENTAL": "Saifullah",
    }
    for keyword, sme in keyword_map.items():
        if keyword in blob:
            return sme
    return None


def suggest_rule_from_feedback(feedback: NotMineFeedback) -> tuple[str, str, str] | None:
    inferred = infer_sme_from_reason(
        feedback.reason,
        feedback.question_tags,
        feedback.org_assessment_title,
    )
    if not inferred:
        return None

    topics = topic_tags(feedback.question_tags)
    for tag in topics:
        core = tag.replace("TOPIC_", "").replace("_MCQ", "").replace("_CODING", "")
        for piece in core.split("_"):
            if len(piece) >= 3:
                return RULE_TYPE_TOPIC, piece, inferred

    title = (feedback.org_assessment_title or "").strip()
    if len(title) >= 4:
        return RULE_TYPE_ASSESSMENT, title[:64], inferred
    return None


def _upsert_rule(db: Session, rule_type: str, marker: str, sme_name: str) -> bool:
    marker = marker.strip()
    if not marker or sme_name not in ASSIGNABLE_SMES:
        return False
    existing = (
        db.query(AssignmentRule)
        .filter(
            AssignmentRule.rule_type == rule_type,
            AssignmentRule.marker == marker,
            AssignmentRule.sme_name == sme_name,
        )
        .first()
    )
    if existing:
        if not existing.active:
            existing.active = True
            existing.priority = min(existing.priority, 3)
            return True
        return False
    db.add(
        AssignmentRule(
            rule_type=rule_type,
            marker=marker,
            sme_name=sme_name,
            priority=3,
            active=True,
        )
    )
    return True


def apply_not_mine_learnings(db: Session) -> dict[str, int]:
    """Turn unapplied Not mine feedback into rules, then re-route tickets."""
    pending = (
        db.query(NotMineFeedback)
        .filter(NotMineFeedback.applied.is_(False))
        .order_by(NotMineFeedback.id.asc())
        .all()
    )
    rules_added = 0
    feedback_applied = 0
    for row in pending:
        suggestion = suggest_rule_from_feedback(row)
        inferred = infer_sme_from_reason(
            row.reason, row.question_tags, row.org_assessment_title
        )
        if suggestion:
            rule_type, marker, sme_name = suggestion
            if _upsert_rule(db, rule_type, marker, sme_name):
                rules_added += 1
        row.inferred_sme = inferred or ""
        row.applied = True
        feedback_applied += 1

    db.commit()
    tickets_updated = reassign_open_tickets(db, skip_not_mine=False)
    not_mine_cleared = 0
    for ticket in db.query(Ticket).filter(Ticket.sme_name == SME_NOT_MINE).all():
        routed = assign_sme(ticket.org_assessment_title, ticket.question_tags, db)
        if routed not in (SME_UNASSIGNED, SME_NOT_MINE):
            ticket.sme_name = routed
            not_mine_cleared += 1
    db.commit()
    return {
        "feedback_applied": feedback_applied,
        "rules_added": rules_added,
        "tickets_rerouted": tickets_updated,
        "not_mine_cleared": not_mine_cleared,
    }


def record_not_mine_feedback(
    db: Session,
    ticket: Ticket,
    *,
    from_sme: str,
    reason: str,
) -> NotMineFeedback:
    row = NotMineFeedback(
        ticket_id=ticket.id,
        from_sme=from_sme,
        reason=reason.strip(),
        org_assessment_title=ticket.org_assessment_title,
        question_tags=ticket.question_tags,
    )
    db.add(row)
    append_learning_point(ticket, from_sme=from_sme, reason=reason)
    return row

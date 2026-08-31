"""Route programme + SME using DB assignment rules (topic + assessment title)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from tickets.config import (
    GRIT_SUBJECTS,
    INTENSIVE_OFFLINE_TITLE_MARKERS,
    NIAT_SKILL_TITLE_MARKERS,
    PROGRAMME_GRIT,
    PROGRAMME_INTENSIVE_OFFLINE,
    PROGRAMME_NIAT_SKILL,
    PROGRAMME_OTHER,
    RULE_TYPE_ASSESSMENT,
    RULE_TYPE_TOPIC,
    SME_NOT_MINE,
    SME_SAIFULLAH,
    SME_UNASSIGNED,
    TOPIC_SME_RULES,
)


def parse_tags(question_tags: str) -> list[str]:
    return [t.strip() for t in (question_tags or "").split(",") if t.strip()]


def topic_tags(question_tags: str) -> list[str]:
    return [t for t in parse_tags(question_tags) if t.upper().startswith("TOPIC_")]


def match_grit_subject(org_assessment_title: str) -> str | None:
    title = (org_assessment_title or "").strip()
    if not title:
        return None
    title_lower = title.lower()
    for subject in sorted(GRIT_SUBJECTS, key=len, reverse=True):
        if subject.lower() in title_lower:
            return subject
    return None


def _title_has_marker(title_lower: str, markers: tuple[str, ...]) -> bool:
    return any(marker in title_lower for marker in markers)


def is_intensive_offline(org_assessment_title: str) -> bool:
    title_lower = (org_assessment_title or "").strip().lower()
    if not title_lower:
        return False
    return _title_has_marker(title_lower, INTENSIVE_OFFLINE_TITLE_MARKERS)


def is_niat_skill_exam(org_assessment_title: str) -> bool:
    title_lower = (org_assessment_title or "").strip().lower()
    if not title_lower:
        return False
    if is_intensive_offline(org_assessment_title):
        return False
    return _title_has_marker(title_lower, NIAT_SKILL_TITLE_MARKERS)


def match_programme(org_assessment_title: str) -> tuple[str, str]:
    subject = match_grit_subject(org_assessment_title)
    if subject:
        return PROGRAMME_GRIT, subject
    if is_intensive_offline(org_assessment_title):
        return PROGRAMME_INTENSIVE_OFFLINE, ""
    if is_niat_skill_exam(org_assessment_title):
        return PROGRAMME_NIAT_SKILL, ""
    return PROGRAMME_OTHER, ""


def _default_topic_rules() -> list[tuple[int, str, str]]:
    """priority, marker, sme — flattened from config for seed / fallback."""
    rules: list[tuple[int, str, str]] = []
    priority = 10
    for sme_name, markers in TOPIC_SME_RULES:
        for marker in markers:
            rules.append((priority, marker, sme_name))
            priority += 10
    return rules


def seed_assignment_rules(db: Session) -> None:
    from tickets.models import AssignmentRule

    if db.query(AssignmentRule).count() > 0:
        return
    for priority, marker, sme_name in _default_topic_rules():
        db.add(
            AssignmentRule(
                rule_type=RULE_TYPE_TOPIC,
                marker=marker,
                sme_name=sme_name,
                priority=priority,
                active=True,
            )
        )
    for priority, marker, sme_name in _default_assessment_rules():
        db.add(
            AssignmentRule(
                rule_type=RULE_TYPE_ASSESSMENT,
                marker=marker,
                sme_name=sme_name,
                priority=priority,
                active=True,
            )
        )
    db.commit()


def _default_assessment_rules() -> list[tuple[int, str, str]]:
    return [
        (5, "UI Engineering", "Viharika"),
        (5, "Server Side Engineering", "Saifullah"),
        (5, "Computational Thinking", "Varsha"),
        (5, "Quantitative Reasoning", "Poojitha Pachava"),
        (5, "Critical Thinking", "Mariyam"),
        (5, "CS Fundamentals", "Saifullah"),
        (5, "SQL", "Varsha"),
    ]


def _load_rules(db: Session | None, rule_type: str) -> list[tuple[int, str, str]]:
    if db is None:
        if rule_type == RULE_TYPE_TOPIC:
            return _default_topic_rules()
        if rule_type == RULE_TYPE_ASSESSMENT:
            return _default_assessment_rules()
        return []
    from tickets.models import AssignmentRule

    rows = (
        db.query(AssignmentRule)
        .filter(AssignmentRule.rule_type == rule_type, AssignmentRule.active.is_(True))
        .order_by(AssignmentRule.priority.asc(), AssignmentRule.id.asc())
        .all()
    )
    return [(r.priority, r.marker, r.sme_name) for r in rows]


def assign_sme_from_assessment_title(
    org_assessment_title: str,
    db: Session | None = None,
) -> str | None:
    title_lower = (org_assessment_title or "").strip().lower()
    if not title_lower:
        return None
    for _priority, marker, sme_name in _load_rules(db, RULE_TYPE_ASSESSMENT):
        if marker.lower() in title_lower:
            return sme_name
    return None


def assign_sme_from_tags(
    question_tags: str,
    db: Session | None = None,
) -> str:
    topics = topic_tags(question_tags)
    if not topics:
        topics = parse_tags(question_tags)
    if not topics:
        return SME_UNASSIGNED

    blob = " ".join(topics).upper()
    for _priority, marker, sme_name in _load_rules(db, RULE_TYPE_TOPIC):
        if marker.upper() in blob:
            return sme_name
    if any(t.upper().startswith("TOPIC_") for t in parse_tags(question_tags)):
        return SME_SAIFULLAH
    return SME_UNASSIGNED


def assign_sme(
    org_assessment_title: str,
    question_tags: str = "",
    db: Session | None = None,
) -> str:
    """
    Prefer assessment-title rules when topic alone is ambiguous;
    then topic-tag rules; then Saifullah for other TOPIC_* / Unassigned.
    """
    by_title = assign_sme_from_assessment_title(org_assessment_title, db)
    by_tags = assign_sme_from_tags(question_tags, db)

    # If title rule hits and tags are empty/unassigned, use title.
    if by_title and by_tags in (SME_UNASSIGNED, SME_SAIFULLAH):
        # Title wins over misc/unassigned tag fallback.
        if by_tags == SME_UNASSIGNED or (
            by_tags == SME_SAIFULLAH and by_title != SME_SAIFULLAH
        ):
            return by_title
    # If both agree or tags found a specific SME, prefer tags for coding/topic specificity
    # unless title matched and tags are unassigned.
    if by_tags != SME_UNASSIGNED and by_tags != SME_SAIFULLAH:
        return by_tags
    if by_title:
        return by_title
    return by_tags


def route_ticket(
    org_assessment_title: str,
    question_tags: str = "",
    db: Session | None = None,
) -> dict[str, str]:
    programme, subject = match_programme(org_assessment_title)
    return {
        "programme": programme,
        "subject": subject,
        "sme_name": assign_sme(org_assessment_title, question_tags, db),
    }


def reassign_open_tickets(db: Session, *, skip_not_mine: bool = True) -> int:
    """Re-apply rules to tickets (does not overwrite Not mine by default)."""
    from tickets.models import Ticket

    updated = 0
    query = db.query(Ticket)
    if skip_not_mine:
        query = query.filter(Ticket.sme_name != SME_NOT_MINE)
    for ticket in query.all():
        routed = route_ticket(ticket.org_assessment_title, ticket.question_tags, db)
        if (
            ticket.programme != routed["programme"]
            or ticket.subject != routed["subject"]
            or ticket.sme_name != routed["sme_name"]
        ):
            ticket.programme = routed["programme"]
            ticket.subject = routed["subject"]
            ticket.sme_name = routed["sme_name"]
            updated += 1
    db.commit()
    return updated

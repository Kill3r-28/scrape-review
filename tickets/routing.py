"""Route tickets to programme + SME from org_assessment_title."""

from __future__ import annotations

from tickets.config import (
    GRIT_SUBJECTS,
    NIAT_SKILL_TITLE_MARKERS,
    PROGRAMME_GRIT,
    PROGRAMME_NIAT_SKILL,
    PROGRAMME_OTHER,
    SME_BY_SUBJECT,
)


def match_grit_subject(org_assessment_title: str) -> str | None:
    title = (org_assessment_title or "").strip()
    if not title:
        return None

    title_lower = title.lower()
    # Prefer longer subject names first (e.g. Critical Thinking & Communication before GenAI).
    for subject in sorted(GRIT_SUBJECTS, key=len, reverse=True):
        if subject.lower() in title_lower:
            return subject
    return None


def is_niat_skill_exam(org_assessment_title: str) -> bool:
    title_lower = (org_assessment_title or "").strip().lower()
    if not title_lower:
        return False
    return any(marker in title_lower for marker in NIAT_SKILL_TITLE_MARKERS)


def route_ticket(org_assessment_title: str) -> dict[str, str]:
    subject = match_grit_subject(org_assessment_title)
    if subject:
        return {
            "programme": PROGRAMME_GRIT,
            "subject": subject,
            "sme_name": SME_BY_SUBJECT.get(subject, "Unassigned"),
        }
    if is_niat_skill_exam(org_assessment_title):
        return {
            "programme": PROGRAMME_NIAT_SKILL,
            "subject": "",
            "sme_name": "Unassigned",
        }
    return {
        "programme": PROGRAMME_OTHER,
        "subject": "",
        "sme_name": "Unassigned",
    }

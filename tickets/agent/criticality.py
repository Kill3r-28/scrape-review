"""Rule-based criticality for student tickets (remark + label)."""

from __future__ import annotations

import re

from sqlalchemy.orm import Session

from tickets.config import (
    CRITICALITY_CRITICAL,
    CRITICALITY_LABELS,
    CRITICALITY_MODERATE,
    CRITICALITY_TRIVIAL,
)
from tickets.models import Ticket

# Empty description: upgrade to Critical when sub-category implies answer/content issue.
CRITICAL_SUB_CATEGORIES: frozenset[str] = frozenset(
    {
        "INCORRECT_ANSWER",
        "WRONG_OUTPUT",
        "INCORRECT_TEST_CASES",
        "INCORRECT_QUESTION",
        "CODE_NOT_RUNNING",
        "SPELLING_OR_GRAMMATICAL_ERROR",
    }
)

MODERATE_SUB_CATEGORIES: frozenset[str] = frozenset(
    {
        "INTERNET_ISSUE",
        "PLATFORM_OTHER",
        "PAGE_CRASHED_OR_BLANK",
        "RUN_TIMEOUT",
        "CANT_START_OR_END_EXAM",
        "CAMERA_MIC_NOT_WORKING",
        "BUTTON_NOT_WORKING",
        "SUBMIT_NOT_WORKING",
        "PROCTORING_OTHER",
        "PERMISSION_NOT_WORKING",
        "SUBMISSION_OTHER",
    }
)

# Internal employee test assessments (snake_case titles like python_while_loop_day5).
INTERNAL_TEST_TITLE = re.compile(r"^[a-z][a-z0-9_]*_(day|week)\d+$")

CRITICAL_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\banswer\s+is\b",
        r"\bwrong\s+answer\b",
        r"\bmarked\s+wrong\b",
        r"\banswer\s+key\b",
        r"\bcorrect\s+answer\b",
        r"\btest\s*cases?\b",
        r"\bwrong\s+input\b",
        r"\btest\s*case\b.{0,40}\b(wrong|issue|incorrect|error|input)\b",
        r"\bunable\s+to\s+see\b.{0,30}\b(my\s+)?(correct\s+)?output\b",
        r"\bunable\s+to\s+see\b.{0,30}\btest\s*cases?\b",
        r"\bwritten\s+the\s+code\b.{0,40}\b(correct\s+)?output\b",
        r"\b0\s+test\s*cases?\s+passed\b",
        r"\bnot\s+passing\b.{0,20}\btest\s*cases?\b",
        r"\bout\s+of\s+syllabus\b",
        r"\bnot\s+taught\b",
        r"\bnot\s+covered\b",
    )
)

MODERATE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.I)
    for p in (
        r"\binternet\b",
        r"\bnetwork\b",
        r"\bconnection\b",
        r"\bdisconnect",
        r"\bslow\b",
        r"\bslowness\b",
        r"\blag\b",
        r"\btimeout\b",
        r"\bcrash",
        r"\bblank\s+page\b",
        r"\bnot\s+loading\b",
        r"\bterminated\b",
        r"\bsubmit\b.{0,20}\b(not\s+working|failed|automatic)",
        r"\bcamera\b",
        r"\bmic(rophone)?\b",
        r"\bproctor",
        r"\bpermission\b",
        r"\bIDE\b.{0,20}\bslow\b",
        r"\bnot\s+visible\b",
        r"\bview\s+report\b",
    )
)

SYSTEM_PROMPT = """You are an assessment-ticket assistant for SMEs.

Classify ticket urgency as Critical, Moderate, or Trivial.

Return ONLY JSON:
{
  "verdict": "Critical" | "Moderate" | "Trivial",
  "remark": "string"
}

VERDICT
- "Critical": answer/test-case/content dispute, wrong key, cannot get correct output, or empty
  report with sub-category like Wrong Answer / Incorrect Test Cases.
- "Moderate": network, IDE slowness, platform, submission, proctoring, or similar infra issues.
- "Trivial": student left no meaningful description (blank or "-") and sub-category does not imply
  an answer/content issue, or the assessment title is an internal employee test
  (e.g. python_while_loop_day5, python_total_week5).

REMARK: 1–3 sentences on what the student reported and what to check.
"""


def _empty_description(description: str) -> bool:
    text = description.strip()
    return not text or text == "-"


def _sub_category(fields: dict) -> str:
    return str(fields.get("sub_category", "")).strip().upper()


def _matches_any(text: str, patterns: tuple[re.Pattern[str], ...]) -> bool:
    return any(p.search(text) for p in patterns)


def _is_internal_test_title(title: str) -> bool:
    return bool(INTERNAL_TEST_TITLE.match(title.strip()))


def classify_criticality(fields: dict) -> tuple[str, str]:
    """Return (criticality label, short remark)."""
    description = str(fields.get("student_description", "")).strip()
    title = str(fields.get("org_assessment_title", "")).strip()
    sub_cat = _sub_category(fields)
    sub_display = str(fields.get("sub_category", "")).strip() or "—"

    if _is_internal_test_title(title):
        return (
            CRITICALITY_TRIVIAL,
            f"Internal employee test assessment ({title}); safe to deprioritise.",
        )

    if _empty_description(description):
        if sub_cat in CRITICAL_SUB_CATEGORIES:
            return (
                CRITICALITY_CRITICAL,
                f"No student text, but sub-category is {sub_display} — treat as answer/content issue.",
            )
        return (
            CRITICALITY_TRIVIAL,
            "Student left no description; no answer/content signal in sub-category.",
        )

    text = description
    if sub_cat in MODERATE_SUB_CATEGORIES or _matches_any(text, MODERATE_PATTERNS):
        return (
            CRITICALITY_MODERATE,
            f"Platform/infra complaint ({sub_display}): {description[:180]}",
        )

    if sub_cat in CRITICAL_SUB_CATEGORIES or _matches_any(text, CRITICAL_PATTERNS):
        return (
            CRITICALITY_CRITICAL,
            f"Answer/test-case/content issue ({sub_display}): {description[:180]}",
        )

    return (
        CRITICALITY_CRITICAL,
        f"Student report ({sub_display}): {description[:180]}",
    )


def ticket_payload(fields: dict) -> str:
    return (
        f"- Assessment: {fields.get('org_assessment_title', '')}\n"
        f"- Programme: {fields.get('programme', '')}\n"
        f"- Category / sub-category: {fields.get('category', '')} / {fields.get('sub_category', '')}\n"
        f"- Question type: {fields.get('question_type', '')}\n"
        f"- Question tags: {fields.get('question_tags', '')}\n"
        f"- Question text: {fields.get('question_text', '')}\n"
        f"- Student description: {fields.get('student_description', '')}\n"
    )


def ticket_fields_from_model(ticket: Ticket) -> dict:
    return {
        "student_description": ticket.student_description,
        "sub_category": ticket.sub_category,
        "category": ticket.category,
        "org_assessment_title": ticket.org_assessment_title,
        "programme": ticket.programme,
        "question_type": ticket.question_type,
        "question_tags": ticket.question_tags,
        "question_text": ticket.question_text,
    }


def assign_criticality_to_ticket(ticket: Ticket) -> str:
    label, remark = classify_criticality(ticket_fields_from_model(ticket))
    ticket.criticality = label
    ticket.critical_remark = remark
    return label


def assign_criticality_all(db: Session, *, only_missing: bool = False) -> dict[str, int]:
    query = db.query(Ticket)
    if only_missing:
        query = query.filter((Ticket.criticality == "") | (Ticket.criticality.is_(None)))
    counts: dict[str, int] = {label: 0 for label in CRITICALITY_LABELS}
    updated = 0
    for ticket in query.all():
        label = assign_criticality_to_ticket(ticket)
        counts[label] = counts.get(label, 0) + 1
        updated += 1
    db.commit()
    return {"updated": updated, **counts}


def valid_criticality(value: str) -> bool:
    return value in CRITICALITY_LABELS


__all__ = [
    "CRITICALITY_CRITICAL",
    "CRITICALITY_LABELS",
    "CRITICALITY_MODERATE",
    "CRITICALITY_TRIVIAL",
    "SYSTEM_PROMPT",
    "assign_criticality_all",
    "assign_criticality_to_ticket",
    "classify_criticality",
    "ticket_payload",
    "valid_criticality",
]

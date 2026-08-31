"""Assign step — topic-tag rules (no LLM)."""

from __future__ import annotations

from tickets.routing import route_ticket


def assign_ticket_fields(org_assessment_title: str, question_tags: str) -> dict[str, str]:
    return route_ticket(org_assessment_title, question_tags)

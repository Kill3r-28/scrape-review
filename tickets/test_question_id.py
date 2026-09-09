"""Tests for question_id extraction and mandatory backfill on upsert."""

from __future__ import annotations

from datetime import date

from scrape import extract_question_id_from_metadata, parse_metadata
from tickets.db import SessionLocal, init_db
from tickets.ingest import (
    _fill_missing_question_fields,
    build_external_report_id,
    upsert_tickets,
)
from tickets.models import Ticket


def test_extract_question_id_from_exam_details():
    assert (
        extract_question_id_from_metadata(
            {"exam_details": {"questions_id": "eca2f408-e2d8-4780-a3d7-2b4a67971ab5"}}
        )
        == "eca2f408-e2d8-4780-a3d7-2b4a67971ab5"
    )


def test_extract_question_id_list_and_empty():
    assert (
        extract_question_id_from_metadata(
            {"exam_details": {"questions_id": ["aaa", "bbb"]}}
        )
        == "aaa"
    )
    assert extract_question_id_from_metadata({"org_assessment_title": "x"}) == ""
    assert extract_question_id_from_metadata({"exam_details": None}) == ""


def test_parse_metadata_json():
    raw = (
        '{"org_assessment_title":"T","exam_details":{"questions_id":'
        '"42b7bbae-e5b5-459a-b0e9-d5b647bafeac"}}'
    )
    parsed = parse_metadata(raw)
    assert parsed["question_id"] == "42b7bbae-e5b5-459a-b0e9-d5b647bafeac"
    assert parsed["org_assessment_title"] == "T"


def test_upsert_fills_missing_question_id_on_existing():
    init_db()
    db = SessionLocal()
    rows = [
        {
            "Org assessment id": "org-1",
            "Org assessment title": "Assessment",
            "User id": "user-1",
            "Category": "CONTENT_ISSUE",
            "Sub category": "CONTENT_OTHER",
            "Description": "need question linked",
            "Creation datetime": "Sept. 9, 2026, 10 a.m.",
            "Question id": "eca2f408-e2d8-4780-a3d7-2b4a67971ab5",
            "Question type": "CODING",
            "Question text": "Write a function",
            "Question tags": "TOPIC_PYTHON",
        }
    ]
    ext = build_external_report_id(rows[0])
    try:
        db.query(Ticket).filter(Ticket.external_report_id == ext).delete()
        db.commit()
        ticket = Ticket(
            external_report_id=ext,
            student_description=rows[0]["Description"],
            status="open",
            sme_name="Unassigned",
            org_assessment_id=rows[0]["Org assessment id"],
            org_assessment_title=rows[0]["Org assessment title"],
            programme="Other",
            subject="",
            user_id=rows[0]["User id"],
            category=rows[0]["Category"],
            sub_category=rows[0]["Sub category"],
            question_id="",
            question_type="",
            question_text="",
            question_tags="",
            report_date="2026-09-09",
            creation_datetime=rows[0]["Creation datetime"],
        )
        db.add(ticket)
        db.commit()

        result = upsert_tickets(db, rows, date(2026, 9, 9))
        assert result["updated"] == 1
        db.refresh(ticket)
        assert ticket.question_id == "eca2f408-e2d8-4780-a3d7-2b4a67971ab5"
        assert ticket.question_type == "CODING"
        assert ticket.question_text == "Write a function"
        assert "TOPIC_PYTHON" in ticket.question_tags
    finally:
        db.query(Ticket).filter(Ticket.external_report_id == ext).delete()
        db.commit()
        db.close()

def test_fill_missing_does_not_overwrite_existing_qid():
    ticket = Ticket(
        external_report_id="x",
        student_description="d",
        question_id="already-set",
        question_type="",
        question_text="",
        question_tags="",
        org_assessment_title="T",
        sme_name="Varsha",
        programme="Other",
        subject="",
    )
    changed = _fill_missing_question_fields(
        ticket,
        {
            "question_id": "new-id",
            "question_type": "MCQ",
            "question_text": "Q?",
            "question_tags": "TOPIC_X",
        },
        None,
    )
    assert changed is True
    assert ticket.question_id == "already-set"
    assert ticket.question_type == "MCQ"

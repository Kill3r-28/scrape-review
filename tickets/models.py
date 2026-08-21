from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from tickets.config import STATUS_OPEN
from tickets.db import Base


class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint(
            "external_report_id",
            name="uq_tickets_external_report_id",
        ),
        Index("ix_tickets_status", "status"),
        Index("ix_tickets_sme_name", "sme_name"),
        Index("ix_tickets_programme", "programme"),
        Index("ix_tickets_report_date", "report_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Stable id from scrape source when available (org_assessment_id + user + created).
    external_report_id: Mapped[str] = mapped_column(String(128), nullable=False)

    student_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=STATUS_OPEN)
    sme_name: Mapped[str] = mapped_column(String(128), nullable=False, default="Unassigned")

    org_assessment_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    org_assessment_title: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    programme: Mapped[str] = mapped_column(String(64), nullable=False, default="Other")
    subject: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sub_category: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    question_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    question_type: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    question_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    question_tags: Mapped[str] = mapped_column(Text, nullable=False, default="")

    report_date: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    creation_datetime: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

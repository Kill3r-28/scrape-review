from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SQLITE = f"sqlite:///{BASE_DIR / 'tickets.db'}"


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return DEFAULT_SQLITE
    # Railway sometimes provides postgres:// — SQLAlchemy wants postgresql://
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    return url


class Base(DeclarativeBase):
    pass


engine = create_engine(
    database_url(),
    connect_args={"check_same_thread": False} if database_url().startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    from tickets import auth as _auth  # noqa: F401
    from tickets import models  # noqa: F401
    from tickets.auth import seed_users
    from tickets.routing import seed_assignment_rules

    Base.metadata.create_all(bind=engine)
    _ensure_ticket_columns()
    db = SessionLocal()
    try:
        seed_users(db)
        seed_assignment_rules(db)
    finally:
        db.close()


def _ensure_ticket_columns() -> None:
    """Add columns create_all will not apply on an existing SQLite file."""
    inspector = inspect(engine)
    if "tickets" not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns("tickets")}
    statements: list[str] = []
    if "criticality" not in existing:
        statements.append(
            "ALTER TABLE tickets ADD COLUMN criticality VARCHAR(64) DEFAULT '' NOT NULL"
        )
    if "critical_remark" not in existing:
        statements.append(
            "ALTER TABLE tickets ADD COLUMN critical_remark TEXT DEFAULT '' NOT NULL"
        )
    if not statements:
        return
    with engine.begin() as conn:
        for sql in statements:
            conn.execute(text(sql))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

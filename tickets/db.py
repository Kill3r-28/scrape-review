from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
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

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_users(db)
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

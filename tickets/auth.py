from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, Session

from tickets.config import ROLE_ADMIN, ROLE_SME, SEED_USERS
from tickets.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("username", name="uq_users_username"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=ROLE_SME)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


def _pbkdf2(password: str, salt: str) -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    )
    return digest.hex()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    return f"pbkdf2_sha256${salt}${_pbkdf2(password, salt)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, salt, digest = stored.split("$", 2)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    return hmac.compare_digest(_pbkdf2(password, salt), digest)


def seed_users(db: Session) -> None:
    """Create default admin + SME accounts if missing. Does not overwrite passwords."""
    for spec in SEED_USERS:
        existing = db.query(User).filter(User.username == spec["username"]).one_or_none()
        if existing:
            continue
        password = spec["password"]
        if spec["role"] == ROLE_ADMIN:
            override = os.getenv("ADMIN_PASSWORD", "").strip()
            if override:
                password = override
        db.add(
            User(
                username=spec["username"],
                display_name=spec["display_name"],
                role=spec["role"],
                password_hash=hash_password(password),
            )
        )
    db.commit()


def reset_seed_passwords(db: Session) -> None:
    """Force-reset passwords from SEED_USERS / ADMIN_PASSWORD (ops helper)."""
    for spec in SEED_USERS:
        user = db.query(User).filter(User.username == spec["username"]).one_or_none()
        if not user:
            continue
        password = spec["password"]
        if spec["role"] == ROLE_ADMIN:
            override = os.getenv("ADMIN_PASSWORD", "").strip()
            if override:
                password = override
        user.password_hash = hash_password(password)
        user.display_name = spec["display_name"]
        user.role = spec["role"]
    db.commit()


def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.query(User).filter(User.username == username.strip().lower()).one_or_none()
    if not user:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


def is_admin(user: User) -> bool:
    return user.role == ROLE_ADMIN

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, Session

from tickets.config import (
    ASSIGNABLE_SMES,
    ROLE_ADMIN,
    ROLE_SME,
    SEED_USERS,
    SME_NOT_MINE,
    SME_UNASSIGNED,
)
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


def list_assignable_smes(db: Session) -> list[str]:
    """Seed roster + any SME users created in the app (for dropdowns)."""
    names: list[str] = []
    seen: set[str] = set()
    for name in ASSIGNABLE_SMES:
        if name not in seen:
            names.append(name)
            seen.add(name)
    for user in (
        db.query(User)
        .filter(User.role == ROLE_SME)
        .order_by(User.display_name.asc())
        .all()
    ):
        display = (user.display_name or "").strip()
        if display and display not in seen:
            names.append(display)
            seen.add(display)
    return names


def list_admin_sme_filters(db: Session) -> list[str]:
    names = list_assignable_smes(db)
    if SME_NOT_MINE not in names:
        names = names + [SME_NOT_MINE]
    return names


def username_from_display_name(display_name: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "" for ch in display_name.strip())
    return (cleaned[:32] or "sme").lower()


def create_sme_user(
    db: Session,
    *,
    display_name: str,
    username: str = "",
    password: str = "",
) -> tuple[User | None, str]:
    """Create an SME login. Returns (user, error_message)."""
    display = display_name.strip()
    if len(display) < 2:
        return None, "Name must be at least 2 characters"
    if display in (SME_UNASSIGNED, SME_NOT_MINE, "Admin"):
        return None, "That name is reserved"

    uname = (username.strip().lower() or username_from_display_name(display))[:64]
    if len(uname) < 2:
        return None, "Username must be at least 2 characters"
    if db.query(User).filter(User.username == uname).one_or_none():
        return None, f"Username '{uname}' already exists"
    if db.query(User).filter(User.display_name == display, User.role == ROLE_SME).one_or_none():
        return None, f"SME '{display}' already exists"

    pwd = password.strip() or f"{display.split()[0].capitalize()}@Grit2026!"
    user = User(
        username=uname,
        display_name=display,
        role=ROLE_SME,
        password_hash=hash_password(pwd),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user, ""


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

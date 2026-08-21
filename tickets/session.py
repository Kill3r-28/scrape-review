"""Signed session cookies for ticket board auth."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from tickets.auth import User, is_admin
from tickets.config import SESSION_COOKIE, SESSION_MAX_AGE_SECONDS
from tickets.db import get_db


def _secret() -> bytes:
    value = os.getenv("SESSION_SECRET", "").strip() or "dev-ticket-session-secret-change-me"
    return value.encode("utf-8")


def create_session_token(user_id: int) -> str:
    payload = {"uid": user_id, "exp": int(time.time()) + SESSION_MAX_AGE_SECONDS}
    body = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    sig = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


def parse_session_token(token: str) -> int | None:
    try:
        body, sig = token.split(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_secret(), body.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(body.encode("ascii")))
    except (json.JSONDecodeError, ValueError):
        return None
    if int(payload.get("exp", 0)) < int(time.time()):
        return None
    return int(payload["uid"])


def set_session(response: Response, user_id: int) -> None:
    # Render sets RENDER=true; force Secure cookies on HTTPS hosts.
    secure_flag = os.getenv("SESSION_SECURE", "").strip().lower() in {"1", "true", "yes"}
    secure = secure_flag or os.getenv("RENDER", "").strip().lower() == "true"
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user_id),
        httponly=True,
        samesite="lax",
        secure=secure,
        max_age=SESSION_MAX_AGE_SECONDS,
        path="/",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    user_id = parse_session_token(token)
    if not user_id:
        return None
    return db.get(User, user_id)


def require_user(
    request: Request, db: Session = Depends(get_db)
) -> User:
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(
            status_code=303,
            detail="Login required",
            headers={"Location": "/login"},
        )
    return user


def require_admin(user: Annotated[User, Depends(require_user)]) -> User:
    if not is_admin(user):
        raise HTTPException(status_code=403, detail="Admin only")
    return user


def login_redirect() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)

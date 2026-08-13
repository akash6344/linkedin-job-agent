"""Auth helpers: password hashing, sessions, current user."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from jobsearch_saas import db
from jobsearch_saas.config import SESSION_DAYS


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        120_000,
    ).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, _ = stored.split("$", 1)
    except ValueError:
        return False
    return hmac.compare_digest(_hash_password(password, salt), stored)


def create_user(*, email: str, password: str, full_name: str = "") -> dict[str, Any]:
    user_id = str(uuid.uuid4())
    now = db.utc_now()
    email_norm = email.strip().lower()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO users (id, email, password_hash, full_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, email_norm, _hash_password(password), full_name.strip(), now),
        )
        _bootstrap_user_rows(conn, user_id, now)
        db.audit(conn, user_id=user_id, action="user.signup", entity_type="user", entity_id=user_id)
    return get_user(user_id)  # type: ignore[return-value]


def create_user_from_google(*, email: str, full_name: str = "") -> dict[str, Any]:
    user_id = str(uuid.uuid4())
    now = db.utc_now()
    email_norm = email.strip().lower()
    password_hash = f"oauth:google:{secrets.token_urlsafe(32)}"
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO users (id, email, password_hash, full_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, email_norm, password_hash, full_name.strip(), now),
        )
        _bootstrap_user_rows(conn, user_id, now)
        db.audit(conn, user_id=user_id, action="user.signup_google", entity_type="user", entity_id=user_id)
    return get_user(user_id)  # type: ignore[return-value]


def _bootstrap_user_rows(conn: Any, user_id: str, now: str) -> None:
    conn.execute(
        "INSERT INTO profiles (user_id, updated_at) VALUES (?, ?)",
        (user_id, now),
    )
    conn.execute(
        "INSERT INTO search_prefs (user_id, updated_at) VALUES (?, ?)",
        (user_id, now),
    )
    conn.execute(
        """
        INSERT INTO entitlements (user_id, plan_id, updated_at, week_key, month_key)
        VALUES (?, 'free', ?, ?, ?)
        """,
        (user_id, now, _week_key(), _month_key()),
    )


def get_or_create_google_user(*, email: str, full_name: str = "") -> tuple[dict[str, Any], bool]:
    user = get_user_by_email(email)
    if user:
        if full_name and not (user.get("full_name") or "").strip():
            with db.connect() as conn:
                conn.execute(
                    "UPDATE users SET full_name = ? WHERE id = ?",
                    (full_name.strip(), user["id"]),
                )
            user = get_user(user["id"])  # type: ignore[assignment]
        return user, False
    return create_user_from_google(email=email, full_name=full_name), True


def get_user(user_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id = ? AND deleted_at IS NULL",
            (user_id,),
        ).fetchone()
        return db.row_to_dict(row)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ? AND deleted_at IS NULL",
            (email.strip().lower(),),
        ).fetchone()
        return db.row_to_dict(row)


def authenticate(email: str, password: str) -> dict[str, Any] | None:
    user = get_user_by_email(email)
    if not user or not verify_password(password, user["password_hash"]):
        return None
    return user


def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=SESSION_DAYS)
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO sessions (token, user_id, expires_at, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, user_id, expires.isoformat(), now.isoformat()),
        )
    return token


def user_from_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT u.*, s.expires_at AS session_expires_at
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ? AND u.deleted_at IS NULL
            """,
            (token,),
        ).fetchone()
        if not row:
            return None
        if datetime.fromisoformat(row["session_expires_at"]) < datetime.now(timezone.utc):
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            return None
        data = db.row_to_dict(row)
        if data:
            data.pop("session_expires_at", None)
            data.pop("password_hash", None)
        return data


def destroy_session(token: str | None) -> None:
    if not token:
        return
    with db.connect() as conn:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def record_consent(
    user_id: str,
    *,
    purpose: str,
    granted: bool,
    notice_version: str = "2026-08-v1",
) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO consents (user_id, purpose, granted, notice_version, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, purpose, 1 if granted else 0, notice_version, db.utc_now()),
        )
        db.audit(
            conn,
            user_id=user_id,
            action="consent.record",
            entity_type="consent",
            detail={"purpose": purpose, "granted": granted, "notice_version": notice_version},
        )


def list_consents(user_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM consents WHERE user_id = ? ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def _week_key() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.isocalendar().year}-W{now.isocalendar().week:02d}"


def _month_key() -> str:
    now = datetime.now(timezone.utc)
    return f"{now.year}-{now.month:02d}"


week_key = _week_key
month_key = _month_key

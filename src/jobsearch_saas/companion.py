"""Companion device auth, upload ingest, and status."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from jobsearch_saas import db
from jobsearch_saas.auth import authenticate
from jobsearch_saas.config import COMPANION_TOKEN_DAYS
from jobsearch_saas.entitlements import (
    active_plan,
    can_companion_upload,
    consume_companion_upload,
)
from jobsearch_saas.jobs.matching import match_user_to_open_jobs
from jobsearch_saas.jobs.sources import NormalizedJob, upsert_job

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def issue_companion_token(
    *,
    email: str,
    password: str,
    device_id: str,
    device_name: str = "",
) -> dict[str, Any]:
    user = authenticate(email, password)
    if not user:
        raise PermissionError("Invalid email or password")
    device_id = (device_id or "").strip() or secrets.token_hex(8)
    device_name = (device_name or "Companion").strip()[:80]
    plan = active_plan(user["id"])
    max_devices = int(plan.get("max_companion_devices") or 1)

    with db.connect() as conn:
        active = conn.execute(
            """
            SELECT device_id FROM companion_tokens
            WHERE user_id = ? AND revoked_at IS NULL
              AND expires_at > ?
            """,
            (user["id"], db.utc_now()),
        ).fetchall()
        active_ids = {r["device_id"] for r in active}
        if device_id not in active_ids and len(active_ids) >= max_devices:
            raise PermissionError(
                f"Device limit reached ({max_devices}). Revoke a device in Settings or upgrade."
            )
        # Revoke prior token for this device
        conn.execute(
            """
            UPDATE companion_tokens SET revoked_at = ?
            WHERE user_id = ? AND device_id = ? AND revoked_at IS NULL
            """,
            (db.utc_now(), user["id"], device_id),
        )
        token = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(days=COMPANION_TOKEN_DAYS)).isoformat()
        conn.execute(
            """
            INSERT INTO companion_tokens
                (token, user_id, device_id, device_name, expires_at, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (token, user["id"], device_id, device_name, expires, db.utc_now(), db.utc_now()),
        )
        conn.execute(
            """
            INSERT INTO companion_status (user_id, device_id, device_name, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                device_id=excluded.device_id,
                device_name=excluded.device_name,
                updated_at=excluded.updated_at
            """,
            (user["id"], device_id, device_name, db.utc_now()),
        )
        db.audit(
            conn,
            user_id=user["id"],
            action="companion.token_issued",
            entity_type="companion_token",
            detail={"device_id": device_id, "device_name": device_name},
        )

    return {
        "token": token,
        "device_id": device_id,
        "expires_at": expires,
        "user": {"id": user["id"], "email": user["email"], "full_name": user["full_name"]},
        "plan": plan,
    }


def user_from_companion_token(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT t.*, u.email, u.full_name, u.deleted_at
            FROM companion_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token = ?
            """,
            (token,),
        ).fetchone()
        if not row or row["deleted_at"] or row["revoked_at"]:
            return None
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            return None
        conn.execute(
            "UPDATE companion_tokens SET last_seen_at = ? WHERE token = ?",
            (db.utc_now(), token),
        )
        return {
            "id": row["user_id"],
            "email": row["email"],
            "full_name": row["full_name"],
            "device_id": row["device_id"],
            "device_name": row["device_name"],
            "companion_token": token,
        }


def revoke_device(user_id: str, device_id: str) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE companion_tokens SET revoked_at = ?
            WHERE user_id = ? AND device_id = ? AND revoked_at IS NULL
            """,
            (db.utc_now(), user_id, device_id),
        )
        db.audit(
            conn,
            user_id=user_id,
            action="companion.device_revoked",
            entity_type="companion_device",
            entity_id=device_id,
        )


def list_devices(user_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT device_id, device_name, created_at, last_seen_at, expires_at, revoked_at
            FROM companion_tokens
            WHERE user_id = ?
            ORDER BY created_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_status(user_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM companion_status WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return db.row_to_dict(row)


def update_status(
    user_id: str,
    *,
    device_id: str = "",
    device_name: str = "",
    linkedin_connected: bool | None = None,
    last_sync_at: str | None = None,
    last_sync_count: int | None = None,
    last_error: str | None = None,
) -> dict[str, Any]:
    current = get_status(user_id) or {}
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO companion_status (
                user_id, device_id, device_name, linkedin_connected,
                last_sync_at, last_sync_count, last_error, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                device_id=COALESCE(NULLIF(excluded.device_id,''), companion_status.device_id),
                device_name=COALESCE(NULLIF(excluded.device_name,''), companion_status.device_name),
                linkedin_connected=COALESCE(excluded.linkedin_connected, companion_status.linkedin_connected),
                last_sync_at=COALESCE(excluded.last_sync_at, companion_status.last_sync_at),
                last_sync_count=COALESCE(excluded.last_sync_count, companion_status.last_sync_count),
                last_error=COALESCE(excluded.last_error, companion_status.last_error),
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                device_id or current.get("device_id") or "",
                device_name or current.get("device_name") or "",
                (
                    1
                    if linkedin_connected is True
                    else 0
                    if linkedin_connected is False
                    else current.get("linkedin_connected") or 0
                ),
                last_sync_at,
                last_sync_count if last_sync_count is not None else current.get("last_sync_count") or 0,
                last_error if last_error is not None else "",
                db.utc_now(),
            ),
        )
    return get_status(user_id) or {}


def _guess_title(text: str, keyword: str = "") -> str:
    for line in (text or "").splitlines():
        line = line.strip()
        if 8 <= len(line) <= 80 and not line.lower().startswith("feed post"):
            return line[:80]
    return (keyword or "LinkedIn hiring post")[:80]


def _guess_company(text: str, author: str = "") -> str:
    if author and len(author) < 80:
        return author
    m = re.search(r"\bat\s+([A-Z][\w&.\- ]{1,40})", text or "")
    return m.group(1).strip() if m else "Unknown company"


def normalize_companion_post(post: dict[str, Any]) -> NormalizedJob:
    url = (post.get("url") or post.get("source_url") or "").strip()
    text = (post.get("post_text") or post.get("description") or "").strip()
    keyword = (post.get("keyword") or "").strip()
    author = (post.get("author") or "").strip()
    title = (post.get("title") or "").strip() or _guess_title(text, keyword)
    company = (post.get("company") or "").strip() or _guess_company(text, author)
    apply_email = (post.get("apply_email") or "").strip()
    if not apply_email:
        found = EMAIL_RE.search(text)
        apply_email = found.group(0) if found else ""
    apply_url = (post.get("apply_url") or "").strip() or None
    external = (post.get("external_id") or "").strip()
    if not external:
        basis = url or f"{title}|{company}|{text[:400]}"
        external = hashlib.sha256(basis.encode()).hexdigest()[:20]
    if not url:
        url = f"https://linkedin.local/companion/{external}"
    return NormalizedJob(
        source="linkedin_companion",
        external_id=external,
        title=title,
        company=company,
        location=(post.get("location") or "India / Remote").strip(),
        description=text[:12000],
        source_url=url,
        apply_email=apply_email or None,
        apply_url=apply_url,
        compensation=(post.get("compensation") or ""),
        posted_at=post.get("posted_at"),
        raw={"origin": "linkedin_companion", "keyword": keyword, "author": author},
    )


def ingest_companion_posts(user_id: str, posts: list[dict[str, Any]]) -> dict[str, Any]:
    accepted = 0
    skipped = 0
    blocked_reason = ""
    job_ids: list[str] = []
    for post in posts:
        ok, reason = can_companion_upload(user_id)
        if not ok:
            blocked_reason = reason
            skipped += len(posts) - accepted
            break
        job = normalize_companion_post(post)
        job_id = upsert_job(job)
        consume_companion_upload(user_id)
        job_ids.append(job_id)
        accepted += 1
    matches: list[dict[str, Any]] = []
    if accepted:
        matches = match_user_to_open_jobs(user_id, limit=min(20, accepted + 5))
    update_status(
        user_id,
        last_sync_at=db.utc_now(),
        last_sync_count=accepted,
        last_error=blocked_reason,
        linkedin_connected=True,
    )
    plan = active_plan(user_id)
    return {
        "accepted": accepted,
        "skipped": skipped,
        "blocked_reason": blocked_reason,
        "job_ids": job_ids,
        "matches_created": len(matches),
        "companion_uploads_remaining": plan.get("companion_uploads_remaining", 0),
    }

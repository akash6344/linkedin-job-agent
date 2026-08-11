"""Draft generation and human-in-the-loop approval."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from jobsearch_saas import db
from jobsearch_saas.email.oauth import get_connection, send_mail_via_oauth
from jobsearch_saas.entitlements import can_create_draft, consume_application


def _primary_resume(user_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM resumes WHERE user_id = ?
            ORDER BY is_primary DESC, created_at DESC LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        return db.row_to_dict(row)


def create_draft_for_match(user_id: str, match_id: str) -> dict[str, Any]:
    ok, reason = can_create_draft(user_id)
    if not ok:
        raise RuntimeError(reason)

    with db.connect() as conn:
        match = conn.execute(
            """
            SELECT m.*, j.title, j.company, j.apply_email, j.apply_url, j.description, j.source
            FROM matches m JOIN jobs j ON j.id = m.job_id
            WHERE m.id = ? AND m.user_id = ?
            """,
            (match_id, user_id),
        ).fetchone()
        if not match:
            raise RuntimeError("Match not found")
        user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        duplicate = None
        apply_email = (match["apply_email"] or "").strip()
        if apply_email:
            duplicate = conn.execute(
                """
                SELECT a.id, j.title, j.company FROM applications a
                JOIN drafts d ON d.id = a.draft_id
                LEFT JOIN jobs j ON j.id = a.job_id
                WHERE a.user_id = ? AND lower(d.to_email) = ? AND a.stage = 'applied'
                ORDER BY a.created_at DESC LIMIT 1
                """,
                (user_id, apply_email.lower()),
            ).fetchone()

    name = (user["full_name"] if user else "") or "Candidate"
    title = match["title"] or "the role"
    company = match["company"] or "your company"
    subject = f"Application for {title} — {name}"
    body = (
        f"Hi,\n\n"
        f"I am writing to apply for the {title} position at {company}. "
        f"Please find my resume attached.\n\n"
        f"Best regards,\n{name}\n"
        f"{user['email'] if user else ''}\n"
        f"{user['phone'] if user else ''}\n"
        f"{user['linkedin_url'] if user else ''}\n"
    )
    resume = _primary_resume(user_id)
    draft_id = str(uuid.uuid4())
    warning = ""
    if duplicate:
        warning = (
            f"You already emailed this address for "
            f"{duplicate['title'] or '-'} @ {duplicate['company'] or '-'}."
        )
    if not apply_email and match["apply_url"]:
        body = (
            f"Checklist for {title} at {company}\n\n"
            f"Apply URL: {match['apply_url']}\n\n"
            f"Suggested pitch:\n{body}"
        )
        subject = f"Form / link apply checklist — {title}"

    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO drafts (
                id, user_id, match_id, resume_id, to_email, subject, body,
                status, duplicate_warning, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'pending_approval', ?, ?, ?)
            """,
            (
                draft_id,
                user_id,
                match_id,
                resume["id"] if resume else None,
                apply_email or None,
                subject,
                body,
                warning,
                now,
                now,
            ),
        )
        conn.execute(
            "UPDATE matches SET status = 'drafted' WHERE id = ? AND user_id = ?",
            (match_id, user_id),
        )
        app_id = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO applications (
                id, user_id, match_id, draft_id, job_id, stage, apply_method, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'drafted', ?, ?, ?)
            """,
            (
                app_id,
                user_id,
                match_id,
                draft_id,
                match["job_id"],
                "email" if apply_email else "link",
                now,
                now,
            ),
        )
        db.audit(conn, user_id=user_id, action="draft.created", entity_type="draft", entity_id=draft_id)

    consume_application(user_id)
    return get_draft(user_id, draft_id)  # type: ignore[return-value]


def get_draft(user_id: str, draft_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT d.*, j.title, j.company, j.source, j.source_url, j.apply_url
            FROM drafts d
            JOIN matches m ON m.id = d.match_id
            JOIN jobs j ON j.id = m.job_id
            WHERE d.id = ? AND d.user_id = ?
            """,
            (draft_id, user_id),
        ).fetchone()
        return db.row_to_dict(row)


def list_drafts(user_id: str, status: str | None = "pending_approval") -> list[dict[str, Any]]:
    sql = """
        SELECT d.*, j.title, j.company, j.source
        FROM drafts d
        JOIN matches m ON m.id = d.match_id
        JOIN jobs j ON j.id = m.job_id
        WHERE d.user_id = ?
    """
    params: list[Any] = [user_id]
    if status:
        sql += " AND d.status = ?"
        params.append(status)
    sql += " ORDER BY d.created_at DESC"
    with db.connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def update_draft(
    user_id: str,
    draft_id: str,
    *,
    subject: str | None = None,
    body: str | None = None,
    to_email: str | None = None,
) -> dict[str, Any]:
    draft = get_draft(user_id, draft_id)
    if not draft:
        raise RuntimeError("Draft not found")
    with db.connect() as conn:
        conn.execute(
            """
            UPDATE drafts SET
                subject = COALESCE(?, subject),
                body = COALESCE(?, body),
                to_email = COALESCE(?, to_email),
                updated_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (subject, body, to_email, db.utc_now(), draft_id, user_id),
        )
    return get_draft(user_id, draft_id)  # type: ignore[return-value]


def approve_and_send(user_id: str, draft_id: str) -> dict[str, Any]:
    """Human-in-the-loop: only send after explicit approval."""
    draft = get_draft(user_id, draft_id)
    if not draft:
        raise RuntimeError("Draft not found")
    if draft["status"] == "sent":
        return draft
    if not draft.get("to_email"):
        raise RuntimeError("No apply email — use the apply URL / form checklist instead.")
    if draft.get("duplicate_warning"):
        # Still allow send, but require caller to acknowledge — UI shows warning.
        pass

    connection = get_connection(user_id)
    if not connection or not connection.get("send_enabled"):
        raise RuntimeError("Connect Gmail via OAuth before sending.")

    resume_path = None
    if draft.get("resume_id"):
        with db.connect() as conn:
            resume = conn.execute(
                "SELECT * FROM resumes WHERE id = ? AND user_id = ?",
                (draft["resume_id"], user_id),
            ).fetchone()
            if resume:
                resume_path = Path(resume["storage_path"])

    send_mail_via_oauth(
        user_id,
        to_email=draft["to_email"],
        subject=draft["subject"],
        body=draft["body"],
        attachment_path=resume_path,
    )
    now = db.utc_now()
    with db.connect() as conn:
        conn.execute(
            "UPDATE drafts SET status = 'sent', sent_at = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (now, now, draft_id, user_id),
        )
        conn.execute(
            "UPDATE matches SET status = 'applied' WHERE id = ? AND user_id = ?",
            (draft["match_id"], user_id),
        )
        conn.execute(
            """
            UPDATE applications SET stage = 'applied', updated_at = ?
            WHERE draft_id = ? AND user_id = ?
            """,
            (now, draft_id, user_id),
        )
        db.audit(conn, user_id=user_id, action="draft.approved_sent", entity_type="draft", entity_id=draft_id)
    return get_draft(user_id, draft_id)  # type: ignore[return-value]


def reject_draft(user_id: str, draft_id: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE drafts SET status = 'rejected', updated_at = ? WHERE id = ? AND user_id = ?",
            (db.utc_now(), draft_id, user_id),
        )
        db.audit(conn, user_id=user_id, action="draft.rejected", entity_type="draft", entity_id=draft_id)

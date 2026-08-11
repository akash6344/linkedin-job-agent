"""DPDP-oriented privacy controls: export, delete, consent history."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from jobsearch_saas import db
from jobsearch_saas.auth import list_consents
from jobsearch_saas.config import UPLOAD_DIR


NOTICE_VERSION = "2026-08-v1"

CONSENT_PURPOSES = (
    {
        "purpose": "job_matching",
        "label": "Job matching",
        "description": "Use my profile, resume, and preferences to find and score job matches.",
    },
    {
        "purpose": "email_sending",
        "label": "Email sending",
        "description": "Send approved application emails from my connected Gmail account.",
    },
    {
        "purpose": "product_updates",
        "label": "Product communications",
        "description": "Send product tips, beta surveys, and billing receipts (not marketing spam).",
    },
)


def export_user_data(user_id: str) -> dict[str, Any]:
    with db.connect() as conn:
        user = db.row_to_dict(
            conn.execute("SELECT id, email, full_name, phone, linkedin_url, github_url, created_at FROM users WHERE id = ?", (user_id,)).fetchone()
        )
        profile = db.row_to_dict(conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone())
        prefs = db.row_to_dict(conn.execute("SELECT * FROM search_prefs WHERE user_id = ?", (user_id,)).fetchone())
        resumes = [dict(r) for r in conn.execute("SELECT id, label, filename, is_primary, created_at FROM resumes WHERE user_id = ?", (user_id,)).fetchall()]
        matches = [dict(r) for r in conn.execute("SELECT * FROM matches WHERE user_id = ?", (user_id,)).fetchall()]
        drafts = [dict(r) for r in conn.execute("SELECT id, match_id, to_email, subject, status, created_at, sent_at FROM drafts WHERE user_id = ?", (user_id,)).fetchall()]
        apps = [dict(r) for r in conn.execute("SELECT * FROM applications WHERE user_id = ?", (user_id,)).fetchall()]
        payments = [dict(r) for r in conn.execute("SELECT id, plan_id, amount_paise, gst_paise, status, created_at, paid_at FROM payments WHERE user_id = ?", (user_id,)).fetchall()]
        audits = [dict(r) for r in conn.execute("SELECT action, entity_type, entity_id, created_at FROM audit_log WHERE user_id = ? ORDER BY id DESC LIMIT 500", (user_id,)).fetchall()]
    return {
        "notice_version": NOTICE_VERSION,
        "exported_at": db.utc_now(),
        "user": user,
        "profile": profile,
        "search_prefs": prefs,
        "resumes": resumes,
        "consents": list_consents(user_id),
        "matches": matches,
        "drafts": drafts,
        "applications": apps,
        "payments": payments,
        "audit_log": audits,
    }


def delete_user_account(user_id: str) -> None:
    """Erase personal data while keeping anonymized payment stubs if needed."""
    user_upload = UPLOAD_DIR / user_id
    if user_upload.exists():
        shutil.rmtree(user_upload, ignore_errors=True)
    with db.connect() as conn:
        for table in (
            "sessions",
            "consents",
            "profiles",
            "resumes",
            "search_prefs",
            "email_connections",
            "entitlements",
            "drafts",
            "applications",
            "matches",
        ):
            conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
        conn.execute(
            "UPDATE payments SET invoice_json = '{}' WHERE user_id = ?",
            (user_id,),
        )
        conn.execute(
            """
            UPDATE users SET
                email = ?, full_name = '', phone = '', linkedin_url = '', github_url = '',
                password_hash = 'deleted', deleted_at = ?
            WHERE id = ?
            """,
            (f"deleted+{user_id}@invalid.local", db.utc_now(), user_id),
        )
        db.audit(conn, user_id=user_id, action="privacy.account_deleted", entity_type="user", entity_id=user_id)


def latest_consent_map(user_id: str) -> dict[str, bool]:
    result = {c["purpose"]: False for c in CONSENT_PURPOSES}
    seen: set[str] = set()
    for row in list_consents(user_id):
        purpose = row["purpose"]
        if purpose in result and purpose not in seen:
            result[purpose] = bool(row["granted"])
            seen.add(purpose)
    return result


def write_export_file(user_id: str) -> Path:
    data = export_user_data(user_id)
    path = UPLOAD_DIR / user_id / "export.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path

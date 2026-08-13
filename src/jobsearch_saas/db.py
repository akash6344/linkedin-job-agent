"""Multi-tenant storage for LetItApply SaaS (SQLite locally, MongoDB when MONGO_URI is set)."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

from jobsearch_saas.config import DATABASE_URL, MONGO_URI, UPLOAD_DIR, use_mongo


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sqlite_path() -> Path:
    parsed = urlparse(DATABASE_URL)
    if parsed.scheme != "sqlite":
        raise RuntimeError("Only sqlite:// URLs are supported for the SQLite backend")
    path = parsed.path
    if path.startswith("/") and len(path) > 1 and path[2] == ":":
        path = path.lstrip("/")
    return Path(path)


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    linkedin_url TEXT NOT NULL DEFAULT '',
    github_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL REFERENCES users(id),
    purpose TEXT NOT NULL,
    granted INTEGER NOT NULL,
    notice_version TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    headline TEXT NOT NULL DEFAULT '',
    years_experience REAL NOT NULL DEFAULT 0,
    skills_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS resumes (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    label TEXT NOT NULL,
    filename TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    is_primary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_prefs (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    roles_json TEXT NOT NULL DEFAULT '[]',
    locations_json TEXT NOT NULL DEFAULT '["India","Remote"]',
    work_modes_json TEXT NOT NULL DEFAULT '["remote","hybrid","onsite"]',
    min_salary_lpa REAL,
    max_years_experience REAL NOT NULL DEFAULT 3,
    exclusions_json TEXT NOT NULL DEFAULT '[]',
    daily_application_limit INTEGER NOT NULL DEFAULT 10,
    preferred_apply_route TEXT NOT NULL DEFAULT 'email',
    auto_send_enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_connections (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    provider TEXT NOT NULL DEFAULT 'gmail',
    email_address TEXT NOT NULL,
    access_token_enc TEXT NOT NULL DEFAULT '',
    refresh_token_enc TEXT NOT NULL DEFAULT '',
    scopes_json TEXT NOT NULL DEFAULT '[]',
    send_enabled INTEGER NOT NULL DEFAULT 0,
    read_enabled INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS entitlements (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    plan_id TEXT NOT NULL DEFAULT 'free',
    valid_until TEXT,
    applications_used_month INTEGER NOT NULL DEFAULT 0,
    matches_used_week INTEGER NOT NULL DEFAULT 0,
    companion_uploads_used_week INTEGER NOT NULL DEFAULT 0,
    week_key TEXT NOT NULL DEFAULT '',
    month_key TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companion_tokens (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    device_id TEXT NOT NULL,
    device_name TEXT NOT NULL DEFAULT '',
    expires_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    revoked_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_companion_user_device
ON companion_tokens(user_id, device_id) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS companion_status (
    user_id TEXT PRIMARY KEY REFERENCES users(id),
    device_id TEXT NOT NULL DEFAULT '',
    device_name TEXT NOT NULL DEFAULT '',
    linkedin_connected INTEGER NOT NULL DEFAULT 0,
    last_sync_at TEXT,
    last_sync_count INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS payments (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    plan_id TEXT NOT NULL,
    razorpay_order_id TEXT,
    razorpay_payment_id TEXT,
    amount_paise INTEGER NOT NULL,
    gst_paise INTEGER NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'INR',
    status TEXT NOT NULL,
    invoice_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    paid_at TEXT
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_url TEXT NOT NULL,
    external_id TEXT,
    title TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    apply_email TEXT,
    apply_url TEXT,
    compensation TEXT NOT NULL DEFAULT '',
    posted_at TEXT,
    ingested_at TEXT NOT NULL,
    compliance_status TEXT NOT NULL DEFAULT 'permitted',
    raw_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_source_ext
ON jobs(source, external_id);

CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    job_id TEXT NOT NULL REFERENCES jobs(id),
    fit_score REAL NOT NULL DEFAULT 0,
    fit_reason TEXT NOT NULL DEFAULT '',
    missing_requirements TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'new',
    created_at TEXT NOT NULL,
    UNIQUE(user_id, job_id)
);

CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    match_id TEXT NOT NULL REFERENCES matches(id),
    resume_id TEXT,
    to_email TEXT,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending_approval',
    duplicate_warning TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    sent_at TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    match_id TEXT REFERENCES matches(id),
    draft_id TEXT REFERENCES drafts(id),
    job_id TEXT REFERENCES jobs(id),
    stage TEXT NOT NULL DEFAULT 'saved',
    apply_method TEXT NOT NULL DEFAULT 'email',
    notes TEXT NOT NULL DEFAULT '',
    follow_up_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL DEFAULT '',
    entity_id TEXT NOT NULL DEFAULT '',
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    idempotency_key TEXT UNIQUE,
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completed_at TEXT,
    last_error TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS qr_payment_submissions (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(id),
    payment_id TEXT NOT NULL REFERENCES payments(id),
    plan_id TEXT NOT NULL,
    payer_name TEXT NOT NULL,
    phone TEXT NOT NULL,
    transaction_id TEXT NOT NULL UNIQUE,
    screenshot_path TEXT NOT NULL,
    amount_paise INTEGER NOT NULL,
    gst_paise INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    admin_notes TEXT NOT NULL DEFAULT '',
    reviewed_by TEXT,
    reviewed_at TEXT,
    created_at TEXT NOT NULL
);
"""


_initialized = False


def _migrate(conn: sqlite3.Connection) -> None:
    """Lightweight additive migrations for existing SQLite files."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(entitlements)").fetchall()}
    if "companion_uploads_used_week" not in cols:
        conn.execute(
            "ALTER TABLE entitlements ADD COLUMN companion_uploads_used_week INTEGER NOT NULL DEFAULT 0"
        )
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if "qr_payment_submissions" not in tables:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS qr_payment_submissions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                payment_id TEXT NOT NULL REFERENCES payments(id),
                plan_id TEXT NOT NULL,
                payer_name TEXT NOT NULL,
                phone TEXT NOT NULL,
                transaction_id TEXT NOT NULL UNIQUE,
                screenshot_path TEXT NOT NULL,
                amount_paise INTEGER NOT NULL,
                gst_paise INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                admin_notes TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL
            );
            """
        )


def init_db() -> None:
    global _initialized
    if _initialized:
        return
    try:
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    if use_mongo():
        from jobsearch_saas.mongo_db import ensure_indexes

        ensure_indexes(MONGO_URI)
        _initialized = True
        return
    path = _sqlite_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
        conn.commit()
    finally:
        conn.close()
    _initialized = True


@contextmanager
def connect() -> Iterator[Any]:
    init_db()
    if use_mongo():
        from jobsearch_saas.mongo_db import connect_mongo

        with connect_mongo(MONGO_URI) as conn:
            yield conn
        return
    conn = sqlite3.connect(_sqlite_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: Any | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


def loads(text: str | None, default: Any = None) -> Any:
    if not text:
        return default
    return json.loads(text)


def audit(
    conn: Any,
    *,
    user_id: str | None,
    action: str,
    entity_type: str = "",
    entity_id: str = "",
    detail: dict[str, Any] | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO audit_log (user_id, action, entity_type, entity_id, detail_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (user_id, action, entity_type, entity_id, dumps(detail or {}), _utc_now()),
    )


def enqueue(
    conn: Any,
    *,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str | None = None,
    available_at: str | None = None,
) -> int:
    cur = conn.execute(
        """
        INSERT OR IGNORE INTO job_queue
            (job_type, payload_json, status, idempotency_key, available_at, created_at)
        VALUES (?, ?, 'pending', ?, ?, ?)
        """,
        (
            job_type,
            dumps(payload),
            idempotency_key,
            available_at or _utc_now(),
            _utc_now(),
        ),
    )
    return int(cur.lastrowid or 0)


utc_now = _utc_now

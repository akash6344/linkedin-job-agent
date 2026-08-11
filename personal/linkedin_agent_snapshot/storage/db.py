"""SQLite storage for seen posts and applications."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from linkedin_agent.config import DB_PATH, DATA_DIR

_db_initialized = False


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    global _db_initialized
    if _db_initialized:
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS posts (
                url TEXT PRIMARY KEY,
                role_tag TEXT NOT NULL,
                keyword TEXT NOT NULL,
                author TEXT,
                post_text TEXT,
                found_at TEXT NOT NULL,
                apply_method TEXT,
                status TEXT NOT NULL,
                company TEXT,
                job_title TEXT,
                apply_email TEXT,
                google_form_url TEXT,
                notes TEXT
            );

            CREATE TABLE IF NOT EXISTS pending_actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_url TEXT NOT NULL,
                action_type TEXT NOT NULL,
                payload TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                resolution TEXT
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    _db_initialized = True


@contextmanager
def _connect():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def is_seen(url: str) -> bool:
    with _connect() as conn:
        row = conn.execute("SELECT 1 FROM posts WHERE url = ?", (url,)).fetchone()
        return row is not None


def already_applied_email(email: str) -> dict[str, Any] | None:
    """Return prior applied record for this inbox (case-insensitive), or None."""
    address = (email or "").strip().lower()
    if not address:
        return None
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT url, company, job_title, found_at, apply_email, status
            FROM posts
            WHERE lower(apply_email) = ?
              AND status = 'applied'
              AND apply_method = 'email'
            ORDER BY found_at DESC
            LIMIT 1
            """,
            (address,),
        ).fetchone()
        return dict(row) if row else None


def save_post(record: dict[str, Any]) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO posts (
                url, role_tag, keyword, author, post_text, found_at,
                apply_method, status, company, job_title, apply_email,
                google_form_url, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["url"],
                record["role_tag"],
                record["keyword"],
                record.get("author"),
                record.get("post_text"),
                record.get("found_at") or _utc_now(),
                record.get("apply_method"),
                record["status"],
                record.get("company"),
                record.get("job_title"),
                record.get("apply_email"),
                record.get("google_form_url"),
                record.get("notes"),
            ),
        )


def add_pending(post_url: str, action_type: str, payload: str = "") -> int:
    with _connect() as conn:
        cur = conn.execute(
            """
            INSERT INTO pending_actions (post_url, action_type, payload, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (post_url, action_type, payload, _utc_now()),
        )
        return int(cur.lastrowid)


def resolve_pending(pending_id: int, resolution: str) -> None:
    with _connect() as conn:
        conn.execute(
            """
            UPDATE pending_actions
            SET resolved_at = ?, resolution = ?
            WHERE id = ?
            """,
            (_utc_now(), resolution, pending_id),
        )


def get_post(url: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM posts WHERE url = ?", (url,)).fetchone()
        return dict(row) if row else None

"""Simple DB-backed background job worker."""

from __future__ import annotations

import json
from typing import Any, Callable

from jobsearch_saas import db
from jobsearch_saas.jobs.matching import match_user_to_open_jobs
from jobsearch_saas.jobs.sources import ingest_for_query


HANDLERS: dict[str, Callable[[dict[str, Any]], None]] = {}


def handler(name: str):
    def deco(fn: Callable[[dict[str, Any]], None]):
        HANDLERS[name] = fn
        return fn

    return deco


@handler("ingest_jobs")
def _ingest(payload: dict[str, Any]) -> None:
    query = payload.get("query") or "software engineer"
    ingest_for_query(query)


@handler("match_user")
def _match(payload: dict[str, Any]) -> None:
    user_id = payload["user_id"]
    match_user_to_open_jobs(user_id, limit=int(payload.get("limit") or 20))


def enqueue_ingest(query: str, *, idempotency_key: str | None = None) -> int:
    with db.connect() as conn:
        return db.enqueue(
            conn,
            job_type="ingest_jobs",
            payload={"query": query},
            idempotency_key=idempotency_key,
        )


def enqueue_match(user_id: str, *, limit: int = 20) -> int:
    with db.connect() as conn:
        return db.enqueue(
            conn,
            job_type="match_user",
            payload={"user_id": user_id, "limit": limit},
            idempotency_key=f"match:{user_id}:{db.utc_now()[:13]}",
        )


def process_one() -> bool:
    with db.connect() as conn:
        row = conn.execute(
            """
            SELECT * FROM job_queue
            WHERE status = 'pending' AND available_at <= ?
            ORDER BY id ASC LIMIT 1
            """,
            (db.utc_now(),),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            "UPDATE job_queue SET status = 'running', attempts = attempts + 1 WHERE id = ?",
            (row["id"],),
        )
        job = dict(row)

    try:
        payload = json.loads(job["payload_json"])
        fn = HANDLERS.get(job["job_type"])
        if not fn:
            raise RuntimeError(f"Unknown job type {job['job_type']}")
        fn(payload)
        with db.connect() as conn:
            conn.execute(
                "UPDATE job_queue SET status = 'done', completed_at = ?, last_error = '' WHERE id = ?",
                (db.utc_now(), job["id"]),
            )
    except Exception as exc:
        with db.connect() as conn:
            conn.execute(
                "UPDATE job_queue SET status = 'failed', last_error = ? WHERE id = ?",
                (str(exc)[:500], job["id"]),
            )
        return True
    return True


def process_all(max_jobs: int = 20) -> int:
    n = 0
    for _ in range(max_jobs):
        if not process_one():
            break
        n += 1
    return n

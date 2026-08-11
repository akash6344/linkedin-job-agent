"""Permitted job source ingestion. LinkedIn scraping is intentionally excluded."""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from jobsearch_saas import db
from jobsearch_saas.config import PERMITTED_SOURCES

USER_AGENT = "LetItApply/0.1 (+https://letitapply.com; job-board aggregator; contact=support@letitapply.com)"


@dataclass
class NormalizedJob:
    source: str
    external_id: str
    title: str
    company: str
    location: str
    description: str
    source_url: str
    apply_email: str | None = None
    apply_url: str | None = None
    compensation: str = ""
    posted_at: str | None = None
    raw: dict[str, Any] | None = None


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _http_get_json(url: str, timeout: int = 25) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_remotive(query: str = "python") -> list[NormalizedJob]:
    """Public Remotive API — permitted commercial source."""
    url = f"https://remotive.com/api/remote-jobs?search={urllib_quote(query)}&limit=50"
    try:
        payload = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    jobs: list[NormalizedJob] = []
    for item in payload.get("jobs") or []:
        jobs.append(
            NormalizedJob(
                source="remotive",
                external_id=str(item.get("id")),
                title=(item.get("title") or "").strip(),
                company=(item.get("company_name") or "").strip(),
                location=(item.get("candidate_required_location") or "Remote").strip(),
                description=(item.get("description") or "")[:12000],
                source_url=item.get("url") or "",
                apply_url=item.get("url"),
                compensation=(item.get("salary") or ""),
                posted_at=item.get("publication_date"),
                raw=item,
            )
        )
    return jobs


def urllib_quote(value: str) -> str:
    from urllib.parse import quote

    return quote(value)


def fetch_remoteok(tag: str = "python") -> list[NormalizedJob]:
    """RemoteOK public JSON feed — permitted; attribution required."""
    url = "https://remoteok.com/api"
    try:
        payload = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    jobs: list[NormalizedJob] = []
    needle = tag.lower()
    for item in payload:
        if not isinstance(item, dict) or not item.get("id") or not item.get("position"):
            continue
        blob = f"{item.get('position','')} {item.get('tags',[])} {item.get('description','')}".lower()
        if needle and needle not in blob:
            continue
        jobs.append(
            NormalizedJob(
                source="remoteok",
                external_id=str(item.get("id")),
                title=(item.get("position") or "").strip(),
                company=(item.get("company") or "").strip(),
                location=(item.get("location") or "Remote").strip(),
                description=(item.get("description") or "")[:12000],
                source_url=item.get("url") or f"https://remoteok.com/remote-jobs/{item.get('id')}",
                apply_url=item.get("apply_url") or item.get("url"),
                compensation=str(item.get("salary_max") or item.get("salary_min") or ""),
                posted_at=str(item.get("date") or ""),
                raw=item,
            )
        )
    return jobs[:40]


def fetch_arbeitnow(query: str = "software") -> list[NormalizedJob]:
    """Arbeitnow public job board API."""
    url = f"https://www.arbeitnow.com/api/job-board-api?search={urllib_quote(query)}"
    try:
        payload = _http_get_json(url)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return []
    jobs: list[NormalizedJob] = []
    for item in payload.get("data") or []:
        jobs.append(
            NormalizedJob(
                source="arbeitnow",
                external_id=hashlib.sha256((item.get("slug") or item.get("url") or "").encode()).hexdigest()[:16],
                title=(item.get("title") or "").strip(),
                company=(item.get("company_name") or "").strip(),
                location=(item.get("location") or "").strip(),
                description=(item.get("description") or "")[:12000],
                source_url=item.get("url") or "",
                apply_url=item.get("url"),
                posted_at=str(item.get("created_at") or ""),
                raw=item,
            )
        )
    return jobs[:40]


def parse_user_paste(
    *,
    title: str,
    company: str,
    description: str,
    location: str = "India",
    apply_email: str = "",
    apply_url: str = "",
    source_url: str = "",
) -> NormalizedJob:
    """User-provided posting — always permitted with user consent."""
    email = (apply_email or "").strip() or None
    if not email:
        found = EMAIL_RE.search(description or "")
        email = found.group(0) if found else None
    digest = hashlib.sha256(f"{title}|{company}|{description[:500]}".encode()).hexdigest()[:16]
    return NormalizedJob(
        source="user_paste",
        external_id=digest,
        title=title.strip(),
        company=company.strip(),
        location=location.strip() or "India",
        description=description.strip()[:12000],
        source_url=source_url or f"https://user.local/paste/{digest}",
        apply_email=email,
        apply_url=apply_url or None,
        raw={"origin": "user_paste"},
    )


SOURCE_FETCHERS: dict[str, Callable[..., list[NormalizedJob]]] = {
    "remotive": fetch_remotive,
    "remoteok": fetch_remoteok,
    "arbeitnow": fetch_arbeitnow,
}


def assert_permitted(source: str) -> None:
    if source not in PERMITTED_SOURCES:
        raise ValueError(
            f"Source '{source}' is not permitted. "
            "Server-side LinkedIn scraping is excluded; use companion uploads or public APIs."
        )


def upsert_job(job: NormalizedJob) -> str:
    assert_permitted(job.source)
    job_id = str(uuid.uuid4())
    with db.connect() as conn:
        existing = conn.execute(
            "SELECT id FROM jobs WHERE source = ? AND external_id = ?",
            (job.source, job.external_id),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE jobs SET title=?, company=?, location=?, description=?, source_url=?,
                    apply_email=?, apply_url=?, compensation=?, posted_at=?, raw_json=?,
                    compliance_status='permitted'
                WHERE id=?
                """,
                (
                    job.title,
                    job.company,
                    job.location,
                    job.description,
                    job.source_url,
                    job.apply_email,
                    job.apply_url,
                    job.compensation,
                    job.posted_at,
                    db.dumps(job.raw or {}),
                    existing["id"],
                ),
            )
            return existing["id"]
        conn.execute(
            """
            INSERT INTO jobs (
                id, source, source_url, external_id, title, company, location, description,
                apply_email, apply_url, compensation, posted_at, ingested_at,
                compliance_status, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'permitted', ?)
            """,
            (
                job_id,
                job.source,
                job.source_url,
                job.external_id,
                job.title,
                job.company,
                job.location,
                job.description,
                job.apply_email,
                job.apply_url,
                job.compensation,
                job.posted_at,
                db.utc_now(),
                db.dumps(job.raw or {}),
            ),
        )
        return job_id


def ingest_for_query(query: str) -> int:
    """Pull from all permitted public APIs for a search query."""
    count = 0
    for name, fetcher in SOURCE_FETCHERS.items():
        try:
            jobs = fetcher(query)
        except Exception:
            continue
        for job in jobs:
            upsert_job(job)
            count += 1
    return count


def source_catalog() -> list[dict[str, str]]:
    return [
        {
            "id": "remotive",
            "name": "Remotive",
            "method": "public_api",
            "compliance": "permitted",
            "notes": "Remote jobs API with attribution",
        },
        {
            "id": "remoteok",
            "name": "RemoteOK",
            "method": "public_json_feed",
            "compliance": "permitted",
            "notes": "Public feed; follow RemoteOK attribution terms",
        },
        {
            "id": "arbeitnow",
            "name": "Arbeitnow",
            "method": "public_api",
            "compliance": "permitted",
            "notes": "Public job-board API",
        },
        {
            "id": "user_paste",
            "name": "Paste a job",
            "method": "user_provided",
            "compliance": "permitted",
            "notes": "User pastes job text / email / form link",
        },
        {
            "id": "user_forwarded_email",
            "name": "Forwarded email",
            "method": "user_provided",
            "compliance": "permitted",
            "notes": "User forwards hiring emails into the product",
        },
        {
            "id": "company_ats_public",
            "name": "Company careers / ATS",
            "method": "public_listing",
            "compliance": "permitted_when_public",
            "notes": "Public Greenhouse/Lever/etc. boards only",
        },
        {
            "id": "linkedin_companion",
            "name": "LinkedIn via Companion",
            "method": "user_device_upload",
            "compliance": "permitted",
            "notes": "Posts uploaded from the user's laptop companion; LinkedIn session never leaves their device",
        },
        {
            "id": "linkedin_scrape",
            "name": "LinkedIn server scrape",
            "method": "prohibited_commercial",
            "compliance": "excluded",
            "notes": "Not run on LetItApply servers; LinkedIn ToS prohibits third-party scraping/bots",
        },
    ]

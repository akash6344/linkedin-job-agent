"""Match jobs to a user's search preferences and profile."""

from __future__ import annotations

import re
import uuid
from typing import Any

from jobsearch_saas import db
from jobsearch_saas.entitlements import can_show_match, consume_match

INDIA_HINTS = re.compile(r"\b(india|bengaluru|bangalore|hyderabad|pune|chennai|mumbai|delhi|noida|gurgaon|gurugram|remote)\b", re.I)
NON_INDIA_ONSITE = re.compile(
    r"\b(onsite|on-site|in[- ]office)\b.{0,40}\b(usa|us|uk|canada|germany|australia|europe)\b|"
    r"\b(usa|us|uk|canada|germany|australia)\b.{0,40}\b(onsite|on-site|in[- ]office)\b",
    re.I,
)


def get_search_prefs(user_id: str) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM search_prefs WHERE user_id = ?", (user_id,)).fetchone()
        if not row:
            return {
                "roles": [],
                "locations": ["India", "Remote"],
                "work_modes": ["remote", "hybrid", "onsite"],
                "max_years_experience": 3,
                "exclusions": [],
                "daily_application_limit": 10,
            }
        data = dict(row)
        return {
            "roles": db.loads(data["roles_json"], []),
            "locations": db.loads(data["locations_json"], ["India", "Remote"]),
            "work_modes": db.loads(data["work_modes_json"], ["remote", "hybrid", "onsite"]),
            "min_salary_lpa": data.get("min_salary_lpa"),
            "max_years_experience": data.get("max_years_experience") or 3,
            "exclusions": db.loads(data["exclusions_json"], []),
            "daily_application_limit": data.get("daily_application_limit") or 10,
            "preferred_apply_route": data.get("preferred_apply_route") or "email",
            "auto_send_enabled": bool(data.get("auto_send_enabled")),
        }


def save_search_prefs(user_id: str, prefs: dict[str, Any]) -> None:
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO search_prefs (
                user_id, roles_json, locations_json, work_modes_json, min_salary_lpa,
                max_years_experience, exclusions_json, daily_application_limit,
                preferred_apply_route, auto_send_enabled, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                roles_json=excluded.roles_json,
                locations_json=excluded.locations_json,
                work_modes_json=excluded.work_modes_json,
                min_salary_lpa=excluded.min_salary_lpa,
                max_years_experience=excluded.max_years_experience,
                exclusions_json=excluded.exclusions_json,
                daily_application_limit=excluded.daily_application_limit,
                preferred_apply_route=excluded.preferred_apply_route,
                auto_send_enabled=excluded.auto_send_enabled,
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                db.dumps(prefs.get("roles") or []),
                db.dumps(prefs.get("locations") or ["India", "Remote"]),
                db.dumps(prefs.get("work_modes") or ["remote", "hybrid", "onsite"]),
                prefs.get("min_salary_lpa"),
                float(prefs.get("max_years_experience") or 3),
                db.dumps(prefs.get("exclusions") or []),
                int(prefs.get("daily_application_limit") or 10),
                prefs.get("preferred_apply_route") or "email",
                1 if prefs.get("auto_send_enabled") else 0,
                db.utc_now(),
            ),
        )


def _score_job(job: dict[str, Any], prefs: dict[str, Any], skills: list[str]) -> tuple[float, str, str]:
    text = f"{job.get('title','')} {job.get('company','')} {job.get('location','')} {job.get('description','')}"
    text_l = text.lower()
    reasons: list[str] = []
    missing: list[str] = []
    score = 0.0

    roles = [r.lower() for r in prefs.get("roles") or []]
    if roles:
        hits = [r for r in roles if r in text_l]
        if hits:
            score += 40
            reasons.append(f"Role keywords matched: {', '.join(hits[:3])}")
        else:
            missing.append("Target role keywords not found")
            score += 5
    else:
        score += 15

    loc = (job.get("location") or "").lower()
    if NON_INDIA_ONSITE.search(text) and "remote" not in loc:
        return 0.0, "Explicit non-India onsite role", "Location mismatch"
    if INDIA_HINTS.search(text) or "remote" in loc or not loc:
        score += 25
        reasons.append("India / remote-friendly location")
    else:
        score += 8
        missing.append("Location unclear for India search")

    if skills:
        skill_hits = [s for s in skills if s.lower() in text_l]
        score += min(25, 5 * len(skill_hits))
        if skill_hits:
            reasons.append(f"Skills overlap: {', '.join(skill_hits[:5])}")
        else:
            missing.append("Few overlapping skills")

    for ex in prefs.get("exclusions") or []:
        if ex and ex.lower() in text_l:
            return 0.0, f"Excluded term: {ex}", ex

    # Soft experience: skip senior-heavy titles for early-career users
    if prefs.get("max_years_experience", 3) <= 3 and re.search(
        r"\b(senior|staff|principal|lead)\b", text_l
    ):
        score *= 0.4
        missing.append("Senior-leaning title")

    if job.get("apply_email"):
        score += 5
        reasons.append("Direct apply email available")
    elif job.get("apply_url"):
        score += 3
        reasons.append("Apply URL available")

    return min(100.0, score), "; ".join(reasons) or "Partial match", "; ".join(missing)


def match_user_to_open_jobs(user_id: str, limit: int = 25) -> list[dict[str, Any]]:
    prefs = get_search_prefs(user_id)
    with db.connect() as conn:
        profile = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
        skills = db.loads(profile["skills_json"], []) if profile else []
        jobs = conn.execute(
            "SELECT * FROM jobs ORDER BY ingested_at DESC LIMIT 300"
        ).fetchall()

    created: list[dict[str, Any]] = []
    for job_row in jobs:
        ok, reason = can_show_match(user_id)
        if not ok:
            break
        job = dict(job_row)
        score, fit_reason, missing = _score_job(job, prefs, skills)
        if score < 25:
            continue
        match_id = str(uuid.uuid4())
        with db.connect() as conn:
            existing = conn.execute(
                "SELECT id FROM matches WHERE user_id = ? AND job_id = ?",
                (user_id, job["id"]),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                """
                INSERT INTO matches (id, user_id, job_id, fit_score, fit_reason, missing_requirements, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 'new', ?)
                """,
                (match_id, user_id, job["id"], score, fit_reason, missing, db.utc_now()),
            )
        consume_match(user_id)
        created.append(
            {
                "id": match_id,
                "job_id": job["id"],
                "fit_score": score,
                "fit_reason": fit_reason,
                "missing_requirements": missing,
                "title": job["title"],
                "company": job["company"],
                "source": job["source"],
            }
        )
        if len(created) >= limit:
            break
    return created


def list_matches(user_id: str, status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    sql = """
        SELECT m.*, j.title, j.company, j.location, j.source, j.source_url,
               j.apply_email, j.apply_url, j.compensation, j.description
        FROM matches m
        JOIN jobs j ON j.id = m.job_id
        WHERE m.user_id = ?
    """
    params: list[Any] = [user_id]
    if status:
        sql += " AND m.status = ?"
        params.append(status)
    sql += " ORDER BY m.fit_score DESC, m.created_at DESC LIMIT ?"
    params.append(limit)
    with db.connect() as conn:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

"""Profile, resume upload, and application tracker helpers."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from jobsearch_saas import db
from jobsearch_saas.config import UPLOAD_DIR


def update_profile(
    user_id: str,
    *,
    full_name: str | None = None,
    phone: str | None = None,
    linkedin_url: str | None = None,
    github_url: str | None = None,
    headline: str | None = None,
    years_experience: float | None = None,
    skills: list[str] | None = None,
    summary: str | None = None,
) -> None:
    with db.connect() as conn:
        if any(v is not None for v in (full_name, phone, linkedin_url, github_url)):
            user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            conn.execute(
                """
                UPDATE users SET
                    full_name = ?, phone = ?, linkedin_url = ?, github_url = ?
                WHERE id = ?
                """,
                (
                    full_name if full_name is not None else user["full_name"],
                    phone if phone is not None else user["phone"],
                    linkedin_url if linkedin_url is not None else user["linkedin_url"],
                    github_url if github_url is not None else user["github_url"],
                    user_id,
                ),
            )
        profile = conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
        conn.execute(
            """
            UPDATE profiles SET
                headline = ?, years_experience = ?, skills_json = ?, summary = ?, updated_at = ?
            WHERE user_id = ?
            """,
            (
                headline if headline is not None else profile["headline"],
                years_experience if years_experience is not None else profile["years_experience"],
                db.dumps(skills) if skills is not None else profile["skills_json"],
                summary if summary is not None else profile["summary"],
                db.utc_now(),
                user_id,
            ),
        )


def get_profile_bundle(user_id: str) -> dict[str, Any]:
    with db.connect() as conn:
        user = db.row_to_dict(conn.execute("SELECT id, email, full_name, phone, linkedin_url, github_url FROM users WHERE id = ?", (user_id,)).fetchone())
        profile = db.row_to_dict(conn.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,)).fetchone())
        resumes = [dict(r) for r in conn.execute("SELECT id, label, filename, is_primary, created_at FROM resumes WHERE user_id = ?", (user_id,)).fetchall()]
    if profile:
        profile["skills"] = db.loads(profile.get("skills_json"), [])
    return {"user": user, "profile": profile, "resumes": resumes}


def save_resume_file(user_id: str, *, filename: str, content: bytes, label: str = "Primary") -> dict[str, Any]:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or "resume.pdf"
    resume_id = str(uuid.uuid4())
    folder = UPLOAD_DIR / user_id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{resume_id}_{safe}"
    path.write_bytes(content)
    with db.connect() as conn:
        count = conn.execute("SELECT COUNT(*) AS c FROM resumes WHERE user_id = ?", (user_id,)).fetchone()["c"]
        is_primary = 1 if count == 0 else 0
        conn.execute(
            """
            INSERT INTO resumes (id, user_id, label, filename, storage_path, is_primary, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (resume_id, user_id, label, safe, str(path), is_primary, db.utc_now()),
        )
        # Naive skill scrape from PDF bytes text if present as plain text
        text = ""
        try:
            text = content.decode("utf-8", errors="ignore")
        except Exception:
            text = ""
        if text and len(text) > 40:
            skills = _guess_skills(text)
            if skills:
                profile = conn.execute("SELECT skills_json FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
                existing = db.loads(profile["skills_json"], []) if profile else []
                merged = sorted(set(existing) | set(skills))
                conn.execute(
                    "UPDATE profiles SET skills_json = ?, updated_at = ? WHERE user_id = ?",
                    (db.dumps(merged), db.utc_now(), user_id),
                )
        db.audit(conn, user_id=user_id, action="resume.uploaded", entity_type="resume", entity_id=resume_id)
    return {"id": resume_id, "filename": safe, "label": label}


def _guess_skills(text: str) -> list[str]:
    catalog = [
        "Python", "Java", "JavaScript", "TypeScript", "React", "Node", "Django", "Flask",
        "FastAPI", "SQL", "PostgreSQL", "MongoDB", "AWS", "Docker", "Kubernetes",
        "Machine Learning", "PyTorch", "TensorFlow", "LLM", "Generative AI", "LangChain",
    ]
    return [s for s in catalog if re.search(rf"\b{re.escape(s)}\b", text, re.I)]


def list_applications(user_id: str) -> list[dict[str, Any]]:
    with db.connect() as conn:
        rows = conn.execute(
            """
            SELECT a.*, j.title, j.company, j.source, j.source_url, d.subject, d.to_email
            FROM applications a
            LEFT JOIN jobs j ON j.id = a.job_id
            LEFT JOIN drafts d ON d.id = a.draft_id
            WHERE a.user_id = ?
            ORDER BY a.updated_at DESC
            """,
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def set_application_stage(user_id: str, application_id: str, stage: str) -> None:
    allowed = {"saved", "drafted", "applied", "replied", "interview", "offer", "rejected"}
    if stage not in allowed:
        raise ValueError("Invalid stage")
    with db.connect() as conn:
        conn.execute(
            "UPDATE applications SET stage = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (stage, db.utc_now(), application_id, user_id),
        )
        db.audit(
            conn,
            user_id=user_id,
            action="application.stage",
            entity_type="application",
            entity_id=application_id,
            detail={"stage": stage},
        )


def dashboard_stats(user_id: str) -> dict[str, int]:
    with db.connect() as conn:
        def count(sql: str, *params: Any) -> int:
            return int(conn.execute(sql, params).fetchone()[0])

        return {
            "new_matches": count("SELECT COUNT(*) FROM matches WHERE user_id=? AND status='new'", user_id),
            "drafts_pending": count("SELECT COUNT(*) FROM drafts WHERE user_id=? AND status='pending_approval'", user_id),
            "applied": count("SELECT COUNT(*) FROM applications WHERE user_id=? AND stage='applied'", user_id),
            "replies": count("SELECT COUNT(*) FROM applications WHERE user_id=? AND stage IN ('replied','interview','offer')", user_id),
        }

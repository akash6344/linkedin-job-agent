#!/usr/bin/env python3
"""Apply to posts saved from scrape_smoke_result.json (no re-scrape)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkedin_agent.apply.email_sender import draft_email, send_application_email  # noqa: E402
from linkedin_agent.config import DRY_RUN, SEARCH_ROLES  # noqa: E402
from linkedin_agent.llm.analyzer import analyze_post, is_valid_apply_email  # noqa: E402
from linkedin_agent.llm.experience import (  # noqa: E402
    is_internship_role,
    meets_experience_requirement,
)
from linkedin_agent.llm.image_text import (  # noqa: E402
    extract_text_from_image_urls,
    merge_image_text,
    needs_image_enrichment,
)
from linkedin_agent.llm.location import meets_location_requirement  # noqa: E402
from linkedin_agent.llm.role_filter import meets_role_requirement  # noqa: E402
from linkedin_agent.notify.service import (  # noqa: E402
    RunSummary,
    notify_email_sent,
    notify_google_form,
    notify_pending_decision,
    send_run_summary,
)
from linkedin_agent.storage.db import already_applied_email, is_seen, save_post  # noqa: E402


def _role_for_keyword(keyword: str) -> dict[str, str]:
    for role in SEARCH_ROLES:
        if role["keyword"].lower() == keyword.lower():
            return role
    # default for smoke keyword
    return SEARCH_ROLES[0]


def _enrich(post: dict, analysis: dict) -> dict:
    image_urls = list(post.get("image_urls") or [])
    if not image_urls or not needs_image_enrichment(post.get("post_text") or "", analysis):
        return analysis
    print(f"  · Reading images for missing details...")
    image_text = extract_text_from_image_urls(image_urls)
    if not image_text:
        return analysis
    post["post_text"] = merge_image_text(post.get("post_text") or "", image_text)
    return analyze_post(post["post_text"], post["keyword"])


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "logs" / "scrape_smoke_result.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    posts = data.get("posts") or []
    started = datetime.now(timezone.utc).isoformat()
    summary = RunSummary(status="success", started_at=started)
    summary.scraped = len(posts)

    print("=" * 60)
    print(f"  APPLY FROM SCRAPE FILE: {src.name}")
    print(f"  posts={len(posts)}  DRY_RUN={DRY_RUN}")
    print("=" * 60)

    for post in posts:
        role = _role_for_keyword(post.get("keyword") or "")
        post = {**post, "role_tag": role["role_tag"]}
        stats = summary.by_role.setdefault(role["role_tag"], {"found": 0, "applied": 0, "notified": 0})

        if is_seen(post["url"]):
            print(f"  Skip (already seen): {post['url'][:70]}")
            summary.skipped += 1
            continue

        analysis = analyze_post(post["post_text"], post["keyword"])
        analysis = _enrich(post, analysis)

        if not analysis.get("is_job_posting"):
            save_post({**post, "status": "skipped", "notes": analysis.get("reason", "not a job post")})
            summary.skipped += 1
            print(f"  Skip (not job): {(analysis.get('reason') or '')[:80]}")
            continue

        summary.job_posts += 1
        stats["found"] += 1

        is_intern, reason = is_internship_role(post["post_text"], analysis)
        if is_intern:
            save_post({**post, "status": "skipped", "company": analysis.get("company"), "job_title": analysis.get("job_title"), "notes": reason})
            summary.skipped += 1
            summary.internship_skipped += 1
            print(f"  Skip (internship): {reason}")
            continue

        loc_ok, loc_reason = meets_location_requirement(post["post_text"], analysis)
        if not loc_ok:
            save_post({**post, "status": "skipped", "company": analysis.get("company"), "job_title": analysis.get("job_title"), "notes": loc_reason})
            summary.skipped += 1
            summary.location_skipped += 1
            print(f"  Skip (location): {loc_reason}")
            continue

        exp_ok, exp_reason = meets_experience_requirement(post["post_text"], analysis)
        if not exp_ok:
            save_post({**post, "status": "skipped", "company": analysis.get("company"), "job_title": analysis.get("job_title"), "notes": exp_reason})
            summary.skipped += 1
            summary.experience_skipped += 1
            print(f"  Skip (experience): {exp_reason}")
            continue

        role_ok, role_reason = meets_role_requirement(post["post_text"], analysis, role["role_tag"])
        if not role_ok:
            save_post({**post, "status": "skipped", "company": analysis.get("company"), "job_title": analysis.get("job_title"), "notes": role_reason})
            summary.skipped += 1
            print(f"  Skip (role): {role_reason}")
            continue

        apply_email = (analysis.get("apply_email") or "").strip()
        if apply_email and not is_valid_apply_email(apply_email):
            print(f"  Skip invalid email: {apply_email!r}")
            apply_email = ""
        form_url = (analysis.get("google_form_url") or "").strip()
        resume_key = role["resume_key"]
        base = {
            **post,
            "company": analysis.get("company"),
            "job_title": analysis.get("job_title"),
            "apply_email": apply_email or None,
            "google_form_url": form_url or None,
        }

        if apply_email:
            prior = already_applied_email(apply_email)
            if prior:
                print(f"  Skip (already emailed): {apply_email}")
                save_post({**base, "status": "skipped", "notes": f"Already applied to {apply_email}"})
                summary.skipped += 1
                continue
            subject, body = draft_email(post, analysis, role["email_template"], resume_key)
            try:
                if DRY_RUN:
                    save_post({**base, "status": "dry_run", "apply_method": "email"})
                    print(f"  DRY_RUN would email {apply_email}")
                else:
                    send_application_email(apply_email, subject, body, resume_key)
                    save_post({**base, "status": "applied", "apply_method": "email", "notes": "apply_from_smoke_scrape"})
                    stats["applied"] += 1
                    summary.emails_sent += 1
                    notify_email_sent(
                        summary, post, apply_email, subject, resume_key,
                        company=analysis.get("company") or "",
                        job_title=analysis.get("job_title") or "",
                    )
                    print(f"  ✓ Applied → {apply_email} | {analysis.get('job_title')} @ {analysis.get('company')}")
            except Exception as exc:
                save_post({**base, "status": "failed", "apply_method": "email", "notes": str(exc)})
                summary.pending += 1
                print(f"  ✗ Email failed {apply_email}: {exc}")
        elif form_url:
            notify_google_form(summary, post, form_url, company=analysis.get("company") or "", job_title=analysis.get("job_title") or "")
            save_post({**base, "status": "notified", "apply_method": "google_form"})
            stats["notified"] += 1
            summary.forms_notified += 1
            print(f"  · Form notified: {form_url[:80]}")
        else:
            save_post({**base, "status": "pending", "apply_method": "manual"})
            notify_pending_decision(summary, post, "No email or Google Form found", company=analysis.get("company") or "", job_title=analysis.get("job_title") or "")
            summary.pending += 1
            print(f"  · Pending (no email/form): {analysis.get('job_title')} @ {analysis.get('company')}")

    print("\n" + "=" * 60)
    print(
        f"  DONE — {summary.emails_sent} emails, {summary.forms_notified} forms, "
        f"{summary.pending} pending, {summary.experience_skipped} exp-skip, "
        f"{summary.internship_skipped} intern-skip, {summary.location_skipped} loc-skip, "
        f"{summary.skipped} other-skip"
    )
    print("=" * 60)
    send_run_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""End-to-end pipeline: scrape → analyze → apply / notify."""

from datetime import datetime, timezone
from typing import Any

from linkedin_agent.apply.email_sender import draft_email, send_application_email
from linkedin_agent.config import DRY_RUN, SEARCH_ROLES
from linkedin_agent.llm.analyzer import analyze_post
from linkedin_agent.llm.experience import (
    is_internship_role,
    meets_experience_requirement,
)
from linkedin_agent.llm.location import meets_location_requirement
from linkedin_agent.notify.service import (
    RunSummary,
    notify_email_sent,
    notify_google_form,
    notify_pending_decision,
)
from linkedin_agent.scrape.service import scrape_with_browser
from linkedin_agent.storage.db import is_seen, save_post


def _role_config(role_tag: str) -> dict[str, str]:
    for role in SEARCH_ROLES:
        if role["role_tag"] == role_tag:
            return role
    raise KeyError(role_tag)


def _pick_resume(role: dict[str, str], analysis: dict[str, Any]) -> str:
    """Always use the resume mapped to the search keyword — no manual review."""
    return role["resume_key"]


async def run_pipeline() -> RunSummary:
    started_at = datetime.now(timezone.utc).isoformat()
    summary = RunSummary(status="success", started_at=started_at)

    print("=" * 60)
    print("  LINKEDIN JOB AGENT")
    print(f"  {started_at}")
    from linkedin_agent.config import BROWSER_MODE, DRY_RUN, MAX_YEARS_EXPERIENCE

    print(f"  DRY_RUN={'ON (Telegram preview only)' if DRY_RUN else 'OFF (live emails)'}")
    print(f"  MAX_EXPERIENCE={MAX_YEARS_EXPERIENCE} years (skip jobs requiring more)")
    print("  SKIP_INTERNSHIPS=yes")
    print("  LOCATION=India or remote only (skip explicit non-India onsite)")
    print(f"  SCRAPE={BROWSER_MODE} (minimized = background Chrome, no headless block)")
    print("  APPLY=email only (no browser)")
    print("=" * 60)

    posts = await scrape_with_browser()
    summary.scraped = len(posts)

    for post in posts:
        role_tag = post["role_tag"]
        role = _role_config(role_tag)
        stats = summary.by_role.setdefault(role_tag, {"found": 0, "applied": 0, "notified": 0})

        if is_seen(post["url"]):
            summary.skipped += 1
            continue

        analysis = analyze_post(post["post_text"], post["keyword"])

        if not analysis.get("is_job_posting"):
            save_post(
                {
                    **post,
                    "status": "skipped",
                    "apply_method": None,
                    "notes": analysis.get("reason", "not a job post"),
                }
            )
            summary.skipped += 1
            continue

        summary.job_posts += 1
        stats["found"] += 1

        is_intern, intern_reason = is_internship_role(post["post_text"], analysis)
        if is_intern:
            print(f"  Skip (internship): {intern_reason}")
            save_post(
                {
                    **post,
                    "status": "skipped",
                    "apply_method": None,
                    "company": analysis.get("company"),
                    "job_title": analysis.get("job_title"),
                    "notes": intern_reason,
                }
            )
            summary.skipped += 1
            summary.internship_skipped += 1
            continue

        loc_ok, loc_reason = meets_location_requirement(post["post_text"], analysis)
        if not loc_ok:
            print(f"  Skip (location): {loc_reason}")
            save_post(
                {
                    **post,
                    "status": "skipped",
                    "apply_method": None,
                    "company": analysis.get("company"),
                    "job_title": analysis.get("job_title"),
                    "notes": loc_reason,
                }
            )
            summary.skipped += 1
            summary.location_skipped += 1
            continue

        exp_ok, exp_reason = meets_experience_requirement(post["post_text"], analysis)
        if not exp_ok:
            print(f"  Skip (experience): {exp_reason}")
            save_post(
                {
                    **post,
                    "status": "skipped",
                    "apply_method": None,
                    "company": analysis.get("company"),
                    "job_title": analysis.get("job_title"),
                    "notes": exp_reason,
                }
            )
            summary.skipped += 1
            summary.experience_skipped += 1
            continue

        apply_email = (analysis.get("apply_email") or "").strip()
        form_url = (analysis.get("google_form_url") or "").strip()
        resume_key = _pick_resume(role, analysis)

        base_record = {
            **post,
            "company": analysis.get("company"),
            "job_title": analysis.get("job_title"),
            "apply_email": apply_email or None,
            "google_form_url": form_url or None,
        }

        if apply_email:
            subject, body = draft_email(post, analysis, role["email_template"], resume_key)

            if DRY_RUN:
                from linkedin_agent.notify.service import notify_email_preview

                notify_email_preview(post, apply_email, subject, body, resume_key)
                save_post({**base_record, "status": "dry_run", "apply_method": "email"})
            else:
                try:
                    send_application_email(apply_email, subject, body, resume_key)
                    save_post({**base_record, "status": "applied", "apply_method": "email"})
                    stats["applied"] += 1
                    summary.emails_sent += 1
                    notify_email_sent(post, apply_email, subject, resume_key)
                except Exception as exc:
                    save_post({**base_record, "status": "failed", "apply_method": "email", "notes": str(exc)})
                    notify_pending_decision(post, f"Email failed: {exc}")

        elif form_url:
            notify_google_form(post, form_url)
            save_post({**base_record, "status": "notified", "apply_method": "google_form"})
            stats["notified"] += 1
            summary.forms_notified += 1

        else:
            save_post({**base_record, "status": "pending", "apply_method": "manual"})
            notify_pending_decision(post, "No email or Google Form found")
            summary.pending += 1

    if summary.scraped == 0:
        summary.status = "no_posts"

    print("\n" + "=" * 60)
    print(f"  DONE — {summary.emails_sent} emails, {summary.forms_notified} forms, "
          f"{summary.pending} pending, {summary.experience_skipped} skipped (experience), "
          f"{summary.internship_skipped} skipped (internship), {summary.location_skipped} skipped (location)")
    print("=" * 60)

    return summary

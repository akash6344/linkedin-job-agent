"""Notifications: Telegram, macOS banners, and one end-of-run email digest."""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from linkedin_agent.apply.email_sender import send_plain_email
from linkedin_agent.config import FORM_NOTIFY_EMAIL, NAME, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from linkedin_agent.links import browse_link, canonical_post_url, enrich_company_url

# Production caps so digests stay readable under high volume.
MAX_DIGEST_ROWS = 40


@dataclass
class DigestItem:
    kind: str  # applied | form | pending
    company: str = ""
    job_title: str = ""
    keyword: str = ""
    post_url: str = ""
    company_url: str = ""
    apply_email: str = ""
    form_url: str = ""
    reason: str = ""
    resume_key: str = ""


@dataclass
class RunSummary:
    status: str = "success"
    started_at: str = ""
    scraped: int = 0
    job_posts: int = 0
    emails_sent: int = 0
    forms_notified: int = 0
    pending: int = 0
    skipped: int = 0
    experience_skipped: int = 0
    internship_skipped: int = 0
    location_skipped: int = 0
    by_role: dict[str, dict[str, int]] = field(default_factory=dict)
    error: str = ""
    applied_items: list[DigestItem] = field(default_factory=list)
    form_items: list[DigestItem] = field(default_factory=list)
    pending_items: list[DigestItem] = field(default_factory=list)

    def short_message(self) -> str:
        if self.error:
            return self.error[:200]
        lines = [
            f"Scraped {self.scraped} posts | {self.job_posts} job posts",
            f"Emails: {self.emails_sent} | Forms: {self.forms_notified} | Pending: {self.pending}",
            f"Skipped — exp: {self.experience_skipped} | intern: {self.internship_skipped} | location: {self.location_skipped}",
        ]
        for role, stats in self.by_role.items():
            lines.append(f"  {role}: {stats}")
        return "\n".join(lines)


def _clean(value: Any, fallback: str = "-") -> str:
    text = (str(value) if value is not None else "").strip()
    return text or fallback


def _item_from_post(
    *,
    kind: str,
    post: dict[str, Any],
    company: str = "",
    job_title: str = "",
    apply_email: str = "",
    form_url: str = "",
    reason: str = "",
    resume_key: str = "",
) -> DigestItem:
    company_name = company or post.get("company") or ""
    permalink = canonical_post_url(post.get("url"))
    company_link = enrich_company_url(post, company=company_name)
    return DigestItem(
        kind=kind,
        company=_clean(company_name),
        job_title=_clean(job_title or post.get("job_title")),
        keyword=_clean(post.get("keyword"), "job"),
        post_url=_clean(permalink, ""),
        company_url=_clean(company_link or post.get("company_url") or "", ""),
        apply_email=_clean(apply_email, ""),
        form_url=_clean(form_url, ""),
        reason=_clean(reason, ""),
        resume_key=_clean(resume_key, ""),
    )


def _link_lines(item: DigestItem) -> list[str]:
    lines: list[str] = []
    if item.post_url:
        lines.append(f"     Post: {item.post_url}")
    if item.company_url and item.company_url != item.post_url:
        lines.append(f"     Company: {item.company_url}")
    return lines


def send_telegram(text: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id": TELEGRAM_CHAT_ID, "text": text[:4096]}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode())
            return bool(result.get("ok"))
    except Exception as exc:
        print(f"  Telegram failed: {exc}")
        return False


def notify_google_form(
    summary: RunSummary,
    post: dict[str, Any],
    form_url: str,
    *,
    company: str = "",
    job_title: str = "",
) -> None:
    """Queue a form row for the end-of-run digest (no per-post email)."""
    summary.form_items.append(
        _item_from_post(
            kind="form",
            post=post,
            company=company,
            job_title=job_title,
            form_url=form_url,
        )
    )


def notify_pending_decision(
    summary: RunSummary,
    post: dict[str, Any],
    reason: str,
    *,
    company: str = "",
    job_title: str = "",
) -> None:
    """Queue a pending row for the end-of-run digest (no per-post email)."""
    summary.pending_items.append(
        _item_from_post(
            kind="pending",
            post=post,
            company=company,
            job_title=job_title,
            reason=reason,
        )
    )


def notify_email_sent(
    summary: RunSummary,
    post: dict[str, Any],
    to_email: str,
    subject: str,
    resume_key: str,
    *,
    company: str = "",
    job_title: str = "",
) -> None:
    """Queue an applied row; keep a light macOS banner only."""
    summary.applied_items.append(
        _item_from_post(
            kind="applied",
            post=post,
            company=company,
            job_title=job_title,
            apply_email=to_email,
            resume_key=resume_key,
            reason=subject,
        )
    )
    _macos_banner("Application sent", f"To {to_email}")


def notify_email_preview(
    post: dict[str, Any],
    to_email: str,
    subject: str,
    body: str,
    resume_key: str,
) -> None:
    text = (
        f"📧 Email preview (DRY RUN)\n\n"
        f"To: {to_email}\n"
        f"Resume: {resume_key}\n"
        f"Subject: {subject}\n\n"
        f"{body}\n\n"
        f"Link: {browse_link(post)}"
    )
    send_telegram(text)


def _format_section(title: str, rows: list[str], total: int) -> str:
    if not rows and total == 0:
        return f"{title}\n  (none)\n"
    body = "\n".join(rows)
    more = ""
    if total > len(rows):
        more = f"\n  … and {total - len(rows)} more (see DB / logs)\n"
    return f"{title}\n{body}{more}\n"


def _row_applied(i: int, item: DigestItem) -> str:
    lines = [
        f"  {i}. {_clean(item.company)} — {_clean(item.job_title)}",
        f"     To: {item.apply_email}" if item.apply_email else "     To: -",
    ]
    lines.extend(_link_lines(item))
    if item.keyword:
        lines.append(f"     Search: {item.keyword}")
    return "\n".join(lines)


def _row_form(i: int, item: DigestItem) -> str:
    lines = [
        f"  {i}. {_clean(item.company)} — {_clean(item.job_title)}",
        f"     Form: {item.form_url}" if item.form_url else "     Form: -",
    ]
    lines.extend(_link_lines(item))
    if item.keyword:
        lines.append(f"     Search: {item.keyword}")
    return "\n".join(lines)


def _row_pending(i: int, item: DigestItem) -> str:
    lines = [
        f"  {i}. {_clean(item.company)} — {_clean(item.job_title)}",
        f"     Reason: {item.reason}" if item.reason else "     Reason: -",
    ]
    lines.extend(_link_lines(item))
    if item.keyword:
        lines.append(f"     Search: {item.keyword}")
    return "\n".join(lines)


def build_run_digest(summary: RunSummary) -> tuple[str, str]:
    """Build one scannable run report (no full LinkedIn post bodies)."""
    applied = summary.applied_items[:MAX_DIGEST_ROWS]
    forms = summary.form_items[:MAX_DIGEST_ROWS]
    pending = summary.pending_items[:MAX_DIGEST_ROWS]

    if summary.error:
        subject = "[Run Report][ERROR] Job Agent — run failed"
    else:
        subject = (
            f"[Run Report] Job Agent — "
            f"{summary.emails_sent} applied · {summary.forms_notified} forms · {summary.pending} pending"
        )

    started = summary.started_at or datetime.now(timezone.utc).isoformat()
    header = [
        "LinkedIn Job Agent — Run Report",
        f"Time (UTC): {started}",
        f"Status: {summary.status}",
        "",
        f"Scraped: {summary.scraped}  |  Job posts: {summary.job_posts}",
        f"Applied: {summary.emails_sent}  |  Forms: {summary.forms_notified}  |  Pending: {summary.pending}",
        (
            f"Skipped — exp: {summary.experience_skipped} | "
            f"intern: {summary.internship_skipped} | location: {summary.location_skipped}"
        ),
    ]
    if summary.error:
        header.extend(["", f"Error: {summary.error[:500]}"])

    sections = [
        "",
        "=" * 56,
        _format_section(
            "APPLICATIONS SENT",
            [_row_applied(i, it) for i, it in enumerate(applied, 1)],
            len(summary.applied_items),
        ),
        "=" * 56,
        _format_section(
            "GOOGLE FORMS — apply manually",
            [_row_form(i, it) for i, it in enumerate(forms, 1)],
            len(summary.form_items),
        ),
        "=" * 56,
        _format_section(
            "PENDING REVIEW — no clear apply email/form",
            [_row_pending(i, it) for i, it in enumerate(pending, 1)],
            len(summary.pending_items),
        ),
        "=" * 56,
        "",
        "Notes:",
        "- Forms and pending are listed separately so you can triage quickly.",
        "- Full LinkedIn post text is omitted on purpose; open the Post link if needed.",
        f"— {NAME}",
    ]

    body = "\n".join(header + sections)
    return subject, body


def _macos_banner(title: str, message: str) -> bool:
    if sys.platform != "darwin":
        return False

    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_msg = (
        message.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", " · ")
        .replace("—", "-")[:180]
    )
    script = (
        f'display notification "{safe_msg}" with title "{safe_title}" '
        f'sound name "Glass"'
    )
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "unknown error").strip()
            print(f"  · macOS banner failed: {err}")
            return False
        print("  ✓ macOS banner sent (check Focus/DND if you don't see it)")
        return True
    except Exception as exc:
        print(f"  · macOS banner error: {exc}")
        return False


def digest_worth_emailing(summary: RunSummary) -> bool:
    """True when there is something actionable, or a failure to report."""
    if summary.error:
        return True
    if summary.emails_sent or summary.forms_notified or summary.pending:
        return True
    if summary.applied_items or summary.form_items or summary.pending_items:
        return True
    return False


def send_run_summary(summary: RunSummary) -> None:
    """Telegram + macOS + digest email only when the run did something useful."""
    title = "LinkedIn Job Agent"
    telegram_body = f"{title}\n\n{summary.short_message()}\n\n— {NAME}"
    if send_telegram(telegram_body):
        print("  ✓ Telegram summary sent")
    elif not TELEGRAM_BOT_TOKEN:
        print("  · Telegram skipped (set TELEGRAM_BOT_TOKEN in .env)")

    banner = (
        f"{summary.emails_sent} emails · {summary.forms_notified} forms · "
        f"{summary.pending} pending · scraped {summary.scraped}"
    )
    if summary.error:
        banner = f"Error: {summary.error[:120]}"
    _macos_banner(title, banner)

    if not digest_worth_emailing(summary):
        print("  · Run digest email skipped (nothing applied / forms / pending)")
        return

    try:
        subject, body = build_run_digest(summary)
        send_plain_email(FORM_NOTIFY_EMAIL, subject, body)
        print(f"  ✓ Run digest emailed to {FORM_NOTIFY_EMAIL}")
    except Exception as exc:
        print(f"  · Run digest email failed: {exc}")

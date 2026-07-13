"""Telegram notifications."""

import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from linkedin_agent.config import NAME, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


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


def notify_google_form(post: dict[str, Any], form_url: str) -> None:
    text = (
        f"📋 Google Form job — apply manually\n\n"
        f"Role search: {post.get('keyword')}\n"
        f"Author: {post.get('author', '?')}\n"
        f"Form: {form_url}\n"
        f"Post: {post.get('url', '')}\n\n"
        f"{post.get('post_text', '')[:500]}"
    )
    send_telegram(text)


def notify_pending_decision(post: dict[str, Any], reason: str) -> None:
    text = (
        f"❓ Need your input\n\n"
        f"Reason: {reason}\n"
        f"Search: {post.get('keyword')}\n"
        f"Post: {post.get('url', '')}\n\n"
        f"{post.get('post_text', '')[:600]}\n\n"
        f"Reply in Telegram: apply / skip / python / ai"
    )
    send_telegram(text)


def notify_email_sent(post: dict[str, Any], to_email: str, subject: str, resume_key: str) -> None:
    text = (
        f"✅ Application sent\n\n"
        f"To: {to_email}\n"
        f"Subject: {subject}\n"
        f"Resume: {resume_key}\n"
        f"Search: {post.get('keyword')}\n"
        f"Post: {post.get('url', '')}"
    )
    send_telegram(text)


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
        f"Post: {post.get('url', '')}"
    )
    send_telegram(text)


def send_run_summary(summary: RunSummary) -> None:
    title = "LinkedIn Job Agent"
    body = f"{title}\n\n{summary.short_message()}\n\n— {NAME}"
    if send_telegram(body):
        print("  ✓ Telegram summary sent")
    elif not TELEGRAM_BOT_TOKEN:
        print("  · Telegram skipped (set TELEGRAM_BOT_TOKEN in .env)")

    if sys.platform == "darwin":
        try:
            msg = summary.short_message().replace('"', "'").replace("\n", " ")
            subprocess.run(
                ["osascript", "-e", f'display notification "{msg}" with title "{title}"'],
                check=False,
                capture_output=True,
            )
        except Exception:
            pass

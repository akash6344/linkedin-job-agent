"""Email application sender with PDF resume attachment."""

import hashlib
import smtplib
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import ollama

from linkedin_agent.config import (
    EMAIL,
    GITHUB_URL,
    GMAIL_ADDRESS,
    GMAIL_APP_PASSWORD,
    LINKEDIN_URL,
    NAME,
    OLLAMA_MODEL,
    PHONE,
    RESUME_FILES,
    RESUMES_DIR,
    TEMPLATES_DIR,
)
from linkedin_agent.llm.role_filter import sanitize_job_title


def _load_template(name: str) -> str:
    path = TEMPLATES_DIR / f"email_{name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


def fill_template(template: str, *, role: str, company: str = "your company") -> str:
    """Substitute known placeholders. Safe against other braces in the body."""
    return (
        template.replace("{role}", role)
        .replace("{company}", company)
        .replace("{title}", role)
    )


def _resume_path(resume_key: str) -> Path:
    filename = RESUME_FILES[resume_key]
    return RESUMES_DIR / filename


def draft_email(
    post: dict[str, Any],
    analysis: dict[str, Any],
    template_key: str,
    resume_key: str,
) -> tuple[str, str]:
    """Return (subject, body) using Ollama + template."""
    company = (analysis.get("company") or "").strip() or "your company"
    title = sanitize_job_title(
        analysis.get("job_title"),
        (post.get("keyword") or "").strip(),
    ) or "the role"
    template = fill_template(_load_template(template_key), role=title, company=company)
    fallback_body = template or (
        f"Hi,\n\nI am writing to apply for the {title} position at {company}. "
        f"Please find my resume attached.\n\nBest regards,\n{NAME}\n{PHONE}\n{LINKEDIN_URL}"
    )

    prompt = f"""Write a concise, professional job application email.

Applicant: {NAME}
Phone: {PHONE}
LinkedIn: {LINKEDIN_URL}
GitHub: {GITHUB_URL}
Role applying for: {title}
Company: {company}

Use this template as style guide (adapt, do not copy verbatim).
IMPORTANT: The role title is already filled in. Never leave placeholders like {{role}} or {{company}}.

{template}

Post context (1-2 lines max from this):
{post.get('post_text', '')[:800]}

Respond with ONLY valid JSON:
{{"subject": "...", "body": "plain text email body, no markdown"}}
"""

    try:
        response = ollama.chat(
            model=OLLAMA_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        import json
        import re

        text = response["message"]["content"]
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            data = json.loads(match.group(0)) if match else {}
        subject = data.get("subject") or f"Application for {title} — {NAME}"
        body = data.get("body") or fallback_body
        # Model sometimes copies unresolved placeholders — scrub them.
        body = fill_template(body, role=title, company=company)
        if "{role}" in body or not body.strip():
            body = fallback_body
        return subject, body
    except Exception:
        return f"Application for {title} — {NAME}", fallback_body


def send_application_email(
    to_email: str,
    subject: str,
    body: str,
    resume_key: str,
) -> None:
    if not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_APP_PASSWORD not set in .env")

    if len(GMAIL_APP_PASSWORD.replace(" ", "")) != 16:
        raise RuntimeError(
            "GMAIL_APP_PASSWORD must be a 16-character Google App Password "
            "(not your normal Gmail password). Create one at: "
            "https://myaccount.google.com/apppasswords"
        )

    resume_file = _resume_path(resume_key)
    if not resume_file.exists():
        raise FileNotFoundError(f"Resume not found: {resume_file}")

    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with resume_file.open("rb") as f:
        part = MIMEApplication(f.read(), Name=resume_file.name)
        part["Content-Disposition"] = f'attachment; filename="{resume_file.name}"'
        msg.attach(part)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD.replace(" ", ""))
            server.sendmail(GMAIL_ADDRESS, [to_email], msg.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            f"Gmail login failed for {GMAIL_ADDRESS}. Use a Google App Password "
            f"(16 chars), not your regular password. "
            f"https://myaccount.google.com/apppasswords — {exc}"
        ) from exc

    print(f"  ✓ Email sent to {to_email}")


def send_manual_application(
    *,
    to_email: str,
    job_title: str,
    company: str,
    post_text: str = "",
    keyword: str = "Python developer hiring",
    resume_key: str = "python_software",
    template_key: str | None = None,
    force: bool = False,
) -> str:
    """Draft + send an application, skipping if this inbox was already emailed.

    Returns status: "sent", "skipped_duplicate", or raises on failure.
    """
    from linkedin_agent.storage.db import already_applied_email, save_post

    prior = already_applied_email(to_email)
    if prior and not force:
        print(
            f"  Skip (already emailed): {to_email} "
            f"(earlier: {prior.get('job_title') or '-'} @ {prior.get('company') or '-'} "
            f"on {prior.get('found_at')})"
        )
        return "skipped_duplicate"

    template_key = template_key or resume_key
    post = {"keyword": keyword, "post_text": post_text or f"{job_title} at {company}"}
    analysis = {"job_title": job_title, "company": company}
    subject, body = draft_email(post, analysis, template_key, resume_key)
    send_application_email(to_email, subject, body, resume_key)

    digest = hashlib.sha256(f"manual|{to_email.lower()}|{job_title}|{company}".encode()).hexdigest()[:16]
    save_post(
        {
            "url": f"https://linkedin.local/manual/{digest}",
            "role_tag": "manual",
            "keyword": keyword,
            "author": "",
            "post_text": post_text[:2000] if post_text else f"Manual apply: {job_title} @ {company}",
            "company": company,
            "job_title": job_title,
            "apply_email": to_email,
            "status": "applied",
            "apply_method": "email",
            "notes": "manual_send",
        }
    )
    return "sent"


def send_plain_email(to_email: str, subject: str, body: str) -> None:
    """Send a plain-text email with no attachment (e.g. form-job alerts to yourself)."""
    if not GMAIL_APP_PASSWORD:
        raise RuntimeError("GMAIL_APP_PASSWORD not set in .env")

    msg = MIMEMultipart()
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD.replace(" ", ""))
            server.sendmail(GMAIL_ADDRESS, [to_email], msg.as_string())
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            f"Gmail login failed for {GMAIL_ADDRESS}. Use a Google App Password "
            f"(16 chars), not your regular password. "
            f"https://myaccount.google.com/apppasswords — {exc}"
        ) from exc

    print(f"  ✓ Notify email sent to {to_email}")

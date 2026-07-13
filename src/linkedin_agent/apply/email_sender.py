"""Email application sender with PDF resume attachment."""

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


def _load_template(name: str) -> str:
    path = TEMPLATES_DIR / f"email_{name}.txt"
    if path.exists():
        return path.read_text(encoding="utf-8")
    return ""


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
    template = _load_template(template_key)
    company = analysis.get("company") or "your company"
    title = analysis.get("job_title") or post.get("keyword", "the role")

    prompt = f"""Write a concise, professional job application email.

Applicant: {NAME}
Phone: {PHONE}
LinkedIn: {LINKEDIN_URL}
GitHub: {GITHUB_URL}
Role applying for: {title}
Company: {company}

Use this template as style guide (adapt, do not copy verbatim):
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
        body = data.get("body") or template
        return subject, body
    except Exception:
        subject = f"Application for {title} — {NAME}"
        body = template or (
            f"Hi,\n\nI am writing to apply for the {title} position at {company}. "
            f"Please find my resume attached.\n\nBest regards,\n{NAME}\n{PHONE}\n{LINKEDIN_URL}"
        )
        return subject, body


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

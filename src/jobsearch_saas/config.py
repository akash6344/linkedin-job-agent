"""India-first job-search SaaS configuration."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

ON_VERCEL = os.environ.get("VERCEL") == "1"


def _default_base_url() -> str:
    explicit = os.environ.get("SAAS_BASE_URL", "").strip()
    if explicit:
        return explicit.rstrip("/")
    if ON_VERCEL:
        host = (
            os.environ.get("VERCEL_PROJECT_PRODUCTION_URL")
            or os.environ.get("VERCEL_URL")
            or ""
        ).strip()
        if host:
            return f"https://{host}".rstrip("/")
    return "http://127.0.0.1:8000"


def _default_database_url() -> str:
    explicit = os.environ.get("SAAS_DATABASE_URL", "").strip()
    if explicit:
        return explicit
    # Serverless filesystem is read-only except /tmp (ephemeral per instance).
    if ON_VERCEL:
        return "sqlite:////tmp/letitapply/saas.db"
    return f"sqlite:///{PROJECT_ROOT / 'data' / 'saas.db'}"


def _default_upload_dir() -> Path:
    explicit = os.environ.get("SAAS_UPLOAD_DIR", "").strip()
    if explicit:
        return Path(explicit)
    if ON_VERCEL:
        return Path("/tmp/letitapply/uploads")
    return PROJECT_ROOT / "data" / "uploads"


APP_NAME = os.environ.get("SAAS_APP_NAME", "LetItApply")
APP_ENV = os.environ.get("SAAS_ENV", "production" if ON_VERCEL else "development")
SECRET_KEY = os.environ.get("SAAS_SECRET_KEY", "dev-only-change-me")
BASE_URL = _default_base_url()
DATABASE_URL = _default_database_url()
UPLOAD_DIR = _default_upload_dir()
SESSION_COOKIE = "letitapply_session"
SESSION_DAYS = int(os.environ.get("SAAS_SESSION_DAYS", "14"))

# Google OAuth (Gmail send) — never store app passwords for SaaS users
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    f"{BASE_URL}/settings/email/callback",
)
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
TOKEN_FERNET_KEY = os.environ.get("SAAS_TOKEN_FERNET_KEY", "")

# Razorpay one-time passes
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "")
GST_RATE = float(os.environ.get("SAAS_GST_RATE", "0.18"))
PRICES_INCLUDE_GST = os.environ.get("SAAS_PRICES_INCLUDE_GST", "0") == "1"

SUPPORT_EMAIL = os.environ.get("SAAS_SUPPORT_EMAIL", "support@letitapply.com")
LEGAL_ENTITY = os.environ.get("SAAS_LEGAL_ENTITY", "LetItApply")

# Free tier quotas
FREE_MATCHES_PER_WEEK = 10
FREE_DRAFTS_PER_MONTH = 3
FREE_COMPANION_UPLOADS_PER_WEEK = 5
MAX_COMPANION_DEVICES = 2
COMPANION_TOKEN_DAYS = int(os.environ.get("SAAS_COMPANION_TOKEN_DAYS", "30"))
COMPANION_DOWNLOAD_URL = os.environ.get(
    "SAAS_COMPANION_DOWNLOAD_URL",
    f"{BASE_URL}/download",
)
# Dev/beta only — never enable in production public deploys
ALLOW_BETA_GRANT = os.environ.get("SAAS_ALLOW_BETA_GRANT", "0") == "1"

PLANS: dict[str, dict] = {
    "free": {
        "name": "Free",
        "amount_inr": 0,
        "days": 0,
        "matches_per_week": FREE_MATCHES_PER_WEEK,
        "applications_per_month": FREE_DRAFTS_PER_MONTH,
        "companion_uploads_per_week": FREE_COMPANION_UPLOADS_PER_WEEK,
        "max_companion_devices": 1,
        "multi_resume": False,
        "followups": False,
        "priority_support": False,
    },
    "search_pass_30": {
        "name": "Job Search Pass",
        "amount_inr": 29900,  # paise
        "days": 30,
        "matches_per_week": 200,
        "applications_per_month": 30,
        "companion_uploads_per_week": 80,
        "max_companion_devices": MAX_COMPANION_DEVICES,
        "multi_resume": False,
        "followups": False,
        "priority_support": False,
    },
    "pro_30": {
        "name": "Pro Search",
        "amount_inr": 69900,
        "days": 30,
        "matches_per_week": 500,
        "applications_per_month": 100,
        "companion_uploads_per_week": 300,
        "max_companion_devices": MAX_COMPANION_DEVICES,
        "multi_resume": True,
        "followups": True,
        "priority_support": True,
    },
    "pro_90": {
        "name": "90-day Pro Pass",
        "amount_inr": 149900,
        "days": 90,
        "matches_per_week": 500,
        "applications_per_month": 100,
        "companion_uploads_per_week": 300,
        "max_companion_devices": MAX_COMPANION_DEVICES,
        "multi_resume": True,
        "followups": True,
        "priority_support": True,
    },
}

# Commercial sources. linkedin_companion = user-device upload only (not server scrape).
PERMITTED_SOURCES = (
    "remotive",
    "remoteok",
    "arbeitnow",
    "user_paste",
    "user_forwarded_email",
    "company_ats_public",
    "linkedin_companion",
)

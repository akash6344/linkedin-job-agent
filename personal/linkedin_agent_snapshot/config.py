"""Application configuration."""

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
        value = value.strip().strip('"').strip("'")
        # App passwords are sometimes pasted with spaces (abcd efgh ijkl mnop)
        if key.strip() == "GMAIL_APP_PASSWORD":
            value = value.replace(" ", "")
        os.environ.setdefault(key.strip(), value)


_load_dotenv()

# Applicant
NAME = "Akash Uppala"
EMAIL = os.environ.get("GMAIL_ADDRESS", "uppalaakash2004@gmail.com")
PHONE = "8688965399"
LINKEDIN_URL = "https://www.linkedin.com/in/akash-uppala-168045259/"
GITHUB_URL = "https://github.com/akash6344"
# Google Form / manual-apply alerts go here (clickable links in Gmail)
FORM_NOTIFY_EMAIL = os.environ.get("FORM_NOTIFY_EMAIL", "uppalaakash2004@gmail.com")

# Six separate LinkedIn searches (one keyword each), past 24 hours
SEARCH_ROLES = [
    {
        "keyword": "Software Engineer hiring",
        "role_tag": "software_engineer",
        "resume_key": "python_software",
        "email_template": "python_software",
    },
    {
        "keyword": "Python developer hiring",
        "role_tag": "python_developer",
        "resume_key": "python_software",
        "email_template": "python_software",
    },
    {
        "keyword": "Backend developer hiring",
        "role_tag": "backend_developer",
        "resume_key": "python_software",
        "email_template": "python_software",
    },
    {
        "keyword": "Full stack developer hiring",
        "role_tag": "fullstack_developer",
        "resume_key": "python_software",
        "email_template": "python_software",
    },
    {
        "keyword": "AI engineer hiring",
        "role_tag": "ai_engineer",
        "resume_key": "ai_engineer",
        "email_template": "ai_engineer",
    },
    {
        "keyword": "Generative AI hiring",
        "role_tag": "generative_ai",
        "resume_key": "ai_engineer",
        "email_template": "ai_engineer",
    },
]

RESUME_FILES = {
    "python_software": "Akash_Uppala_Resume.pdf",
    "ai_engineer": "Akash_Uppala_Resume(AI).pdf",
}

OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.1")
MAX_YEARS_EXPERIENCE = int(os.environ.get("MAX_YEARS_EXPERIENCE", "3"))
MAX_POSTS_PER_SEARCH = int(os.environ.get("MAX_POSTS_PER_SEARCH", "80"))
SEARCH_DELAY_SEC = int(os.environ.get("SEARCH_DELAY_SEC", "15"))
SCROLL_COUNT = int(os.environ.get("SCROLL_COUNT", "12"))
PAGE_LOAD_DELAY_SEC = 3
# How often LaunchAgent runs (seconds). Default 30 minutes.
SCHEDULE_INTERVAL_SEC = int(os.environ.get("SCHEDULE_INTERVAL_SEC", "1800"))

# minimized = real Chrome off-screen (works with LinkedIn). headless often returns 0 posts.
BROWSER_MODE = os.environ.get("LINKEDIN_BROWSER_MODE", "minimized").lower()
# Legacy flag — only used if LINKEDIN_BROWSER_MODE unset
if "LINKEDIN_BROWSER_MODE" not in os.environ and os.environ.get("LINKEDIN_HEADLESS", "1") == "1":
    BROWSER_MODE = "headless"
elif "LINKEDIN_BROWSER_MODE" not in os.environ and os.environ.get("LINKEDIN_HEADLESS") == "0":
    BROWSER_MODE = "visible"

HEADLESS = BROWSER_MODE == "headless"
HIDE_CHROME = os.environ.get("LINKEDIN_HIDE_CHROME", "1") == "1"
USE_CHROME_CHANNEL = os.environ.get("LINKEDIN_USE_CHROME", "1") == "1"
DRY_RUN = os.environ.get("DRY_RUN", "0") == "1"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

GMAIL_ADDRESS = os.environ.get("GMAIL_ADDRESS", EMAIL)
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")

DATA_DIR = PROJECT_ROOT / "data"
# Personal CLI assets live under personal/ (rollback safety; not shipped as SaaS defaults)
RESUMES_DIR = PROJECT_ROOT / "personal" / "resumes"
TEMPLATES_DIR = PROJECT_ROOT / "personal" / "templates"
BROWSER_DATA_DIR = PROJECT_ROOT / ".linkedin_browser"
DB_PATH = DATA_DIR / "jobs.db"
LOGS_DIR = PROJECT_ROOT / "logs"

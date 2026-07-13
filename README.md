# LinkedIn Job Agent

Automates job discovery from **LinkedIn posts** (not the Jobs tab), classifies postings with local **Ollama**, sends email applications with the right resume PDF, and notifies you on **Telegram** for Google Forms or unclear cases.

## Search setup

Runs **3 separate searches** per cycle:

| Search | Resume PDF |
|--------|------------|
| Software Engineer hiring | `resumes/Akash_Uppala_Resume.pdf` |
| AI engineer hiring | `resumes/Akash_Uppala_Resume(AI).pdf` |
| Python developer hiring | `resumes/Akash_Uppala_Resume.pdf` |

Filters: **Posts → Latest → Past 24 hours**

## Quick start

```bash
cd ~/linkedin-job-agent
cp .env.example .env
# Add TELEGRAM_*, GMAIL_APP_PASSWORD to .env

# Place your PDFs in resumes/ (already configured):
# resumes/Akash_Uppala_Resume.pdf       — Software Engineer hiring + Python developer hiring
# resumes/Akash_Uppala_Resume(AI).pdf   — AI engineer hiring

pip install -e .
python -m playwright install chromium

# First run — log in to LinkedIn (visible browser, session saved)
python -m linkedin_agent login

# Run pipeline in background (no Chrome window; uses saved session)
# Emails are sent via Gmail — no browser for applying
python -m linkedin_agent run
```

## Environment

| Variable | Description |
|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your chat ID |
| `GMAIL_ADDRESS` | Sender email |
| `GMAIL_APP_PASSWORD` | Gmail app password |
| `DRY_RUN` | `1` = preview on Telegram; `0` = send emails |
| `LINKEDIN_BROWSER_MODE` | `minimized` (default, background Chrome), `headless`, or `visible` |
| `LINKEDIN_HIDE_CHROME` | `1` = keep Chrome off-screen during scrape (macOS) |
| `SEARCH_DELAY_SEC` | Pause between role searches (default 15s) |
| `SCROLL_COUNT` | Scroll passes per search (default 12) |
| `MAX_POSTS_PER_SEARCH` | Cap posts kept per keyword (default 80) |
| `SCHEDULE_INTERVAL_SEC` | LaunchAgent interval in seconds (default 1800 = 30 min) |

## Commands

- `python -m linkedin_agent login` — save LinkedIn session
- `python -m linkedin_agent run` — scrape → analyze → apply/notify

## Scheduling (every 30 minutes + on wake)

```bash
bash scripts/setup_scheduler.sh
```

This installs:
- **Every 30 minutes** — regular scrape/apply run (override with `SCHEDULE_INTERVAL_SEC`)
- **On Mac wake** — runs immediately when you open the laptop from sleep (while logged in)

Logs: `logs/cron.log` (scheduled), `logs/wake.log` (wake listener)

Requires Ollama running locally with `llama3.1`.

# LinkedIn Job Agent + LetItApply

Two products live in this repo:

1. **Personal CLI agent** (`linkedin_agent`) — your private LinkedIn-post pipeline (email apply + Telegram).
2. **LetItApply SaaS** (`jobsearch_saas`) — multi-tenant web copilot for Indian early-career candidates: match feed, human-approved drafts, Gmail OAuth, Razorpay passes.

> Commercial SaaS does **not** sell LinkedIn scraping. See `/legal/sources` and `docs/product/mvp.md`.

## Personal CLI (existing)

Automates job discovery from **LinkedIn posts** (not the Jobs tab), classifies postings with local **Ollama**, sends email applications with the right resume PDF, and notifies you on **Telegram** for Google Forms or unclear cases.

### Quick start

```bash
cd ~/linkedin-job-agent
cp .env.example .env
pip install -e .
python -m playwright install chromium
python -m linkedin_agent login
python -m linkedin_agent run
```

## LetItApply SaaS

India-first job-search copilot with a [LoopCV](https://www.loopcv.pro/)-inspired setup flow — but every send waits for your approval.

**Companion (Electron):** searches LinkedIn on the user's laptop and syncs posts to the cloud. See [`companion/README.md`](companion/README.md) and [`docs/product/companion-beta-guide.md`](docs/product/companion-beta-guide.md).

```bash
pip install -e ".[saas]"
bash scripts/run_saas.sh
# → http://127.0.0.1:8000

cd companion && npm install && LETITAPPLY_API=http://127.0.0.1:8000 npm start
```

Set `GOOGLE_CLIENT_*` and `RAZORPAY_*` in `.env` for production email and payments.

Docs: `docs/product/mvp.md`, `docs/product/companion-beta-guide.md`, `docs/validation/`, `docs/legal/`




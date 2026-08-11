# LetItApply Companion

Desktop helper for normal users. Runs on **their laptop**, opens Chrome, searches LinkedIn with their login, and uploads posts to LetItApply cloud.

## Requirements (beta)

- LetItApply website running (`uvicorn …`)
- Python 3.10+ with this repo installed (`pip install -e ".[saas]"`)
- Playwright Chromium (`python -m playwright install chromium`)
- Node 18+ for the Electron UI

## Run (dev)

```bash
# Terminal 1 — API
bash scripts/run_saas.sh

# Terminal 2 — Companion UI
cd companion
npm install
LETITAPPLY_API=http://127.0.0.1:8000 npm start
```

## Buttons

1. **Sign in** — same LetItApply email/password  
2. **Connect LinkedIn** — Chrome opens; user logs in once  
3. **Start searching** — scrape on laptop → upload to API (quota checked)  
4. **Open dashboard** — approve drafts on the website  

## Pack installers (later)

```bash
cd companion
npm run dist
```

Host the built DMG/EXE and link from `/download`.

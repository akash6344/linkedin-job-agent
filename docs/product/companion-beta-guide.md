# LetItApply Companion — beta install guide

For non-technical beta testers (25–50 people). Goal: signup → companion Start → see matches in under 20 minutes.

## What testers need

- A computer (Mac preferred for this beta)
- A LinkedIn account they can log into
- A Gmail account (for later Approve & send)
- Stable internet

## Setup checklist (helper / you)

1. Host LetItApply API somewhere reachable (or give them `http://YOUR_IP:8000` on same Wi‑Fi for local beta).
2. Confirm `/download` page loads.
3. Give each tester a beta invite + optional **Grant beta Pro** from `/billing` after they sign up.

## Tester steps (plain language)

1. Open LetItApply in the browser → **Create account**.
2. Finish onboarding (resume + roles).
3. Open **Companion** in the menu (or `/download`).
4. On their laptop, run the Companion app (beta: you start it for them or share the `npm start` steps once).
5. In Companion:
   - Sign in with the same email/password
   - **Connect LinkedIn** (Chrome opens — they log in)
   - **Start searching**
6. Click **Open dashboard** → review matches → **Draft** → **Approve & send** (after Gmail connect).

## Success metrics to log

| Metric | Target |
|--------|--------|
| Finished onboarding | ≥60% |
| Companion sync succeeded once | ≥50% |
| Approved at least one draft | ≥40% |
| Returned week 2 | ≥40% |

Use `docs/validation/beta-tracker.csv`.

## Support scripts (copy/paste for Mac beta)

```bash
# One-time on tester Mac (you help once)
cd ~/linkedin-job-agent   # or unzip path
python3 -m pip install -e ".[saas]"
python3 -m playwright install chromium
cd companion && npm install

# Every session
# Terminal A
bash scripts/run_saas.sh
# Terminal B
cd companion && LETITAPPLY_API=http://127.0.0.1:8000 npm start
```

## Rules to remind testers

- Approve before send — nothing emails without their click.
- LinkedIn login stays on their laptop.
- If Companion says upgrade / quota, they hit weekly upload limit — upgrade pass or wait.

## After beta

- Package Electron DMG/EXE (`cd companion && npm run dist`) and host the file; link from `/download`.
- Keep server-side LinkedIn scrape **off**; only companion uploads (`linkedin_companion`).

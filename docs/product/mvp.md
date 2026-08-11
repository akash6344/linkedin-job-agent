# LetItApply — product MVP

## Promise

Spend 15 minutes setting up; review high-match applications in one place; send better applications every day.

Do **not** promise interviews, jobs, or unlimited auto-apply.

## Brand

- Product name: **LetItApply**
- Companion: Electron desktop app on the user’s laptop for LinkedIn search
- Positioning: LoopCV-like simplicity with human-approved sends

## Surfaces

| Screen | Purpose |
|--------|---------|
| Landing | Brand-first hero, companion in 3-step flow, pricing |
| Onboarding | Profile, resume, prefs, OAuth, preview |
| Today | Companion status, stats, matches, drafts |
| Download | Companion install instructions |
| Match feed | Fit score, source (incl. `linkedin_companion`), draft |
| Draft workspace | Edit + Approve & send |
| Tracker | Pipeline stages |
| Settings | Gmail, companion devices, consents, export/delete |
| Billing | Passes with companion upload quotas |

## Run locally

```bash
pip install -e ".[saas]"
bash scripts/run_saas.sh
cd companion && npm install && LETITAPPLY_API=http://127.0.0.1:8000 npm start
```

See `docs/product/companion-beta-guide.md`.

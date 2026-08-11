# Personal rollback (not part of LetItApply SaaS)

This folder isolates your **private LinkedIn CLI agent** and PII so the SaaS product does not ship or fall back to them.

## Contents

| Path | Purpose |
|------|---------|
| `linkedin_agent_snapshot/` | Frozen copy of the personal agent at cleanup time — restore from here if needed |
| `resumes/` | Your PDF resumes (used only by the personal CLI) |
| `templates/` | Your email body templates (`email_*.txt`) |
| `text.txt` | Scratch / personal notes — keep out of product code |

## Run the personal CLI (still uses live `src/linkedin_agent`)

Live code under `src/linkedin_agent` still runs your private pipeline, but resumes/templates now resolve from this folder:

```bash
# from repo root, with .venv and .env as before
python -m linkedin_agent
```

## Restore from snapshot

If you need to roll back the agent package itself:

```bash
cp -R personal/linkedin_agent_snapshot/* src/linkedin_agent/
# then restart any LaunchAgent / scheduled runs
```

Do **not** point Companion or SaaS at this folder. Companion must use roles from the signed-in LetItApply account only.

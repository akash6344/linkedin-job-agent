# LetItApply — architecture roadmap

Current MVP is a **Python modular monolith**: FastAPI + Jinja templates + SQLite + DB-backed job queue + Gmail OAuth + Razorpay one-time passes. Personal LinkedIn CLI (`linkedin_agent`) stays separate and is **not** the commercial scrape path.

This note merges findings from architecture assessment and India-first stack research for the next production steps.

## What is already in place

| Concern | Current MVP |
|---------|-------------|
| Web | FastAPI + Jinja (`jobsearch_saas`) |
| Tenancy | Per-user rows in shared SQLite |
| Jobs | `job_queue` table + worker helpers |
| Email | Gmail OAuth (`gmail.send`), encrypted tokens |
| Billing | Razorpay Checkout / Payment Links + webhook |
| Privacy | Consent purposes, export, delete |
| Sources | Remotive / RemoteOK / Arbeitnow / user paste |

## Recommended production upgrades (order)

1. **PostgreSQL + Alembic** — migrate off SQLite; add `tenant_id` indexes; optional RLS as defense-in-depth (`SET LOCAL app.tenant_id`).
2. **Isolate Playwright** — if any browser job is added later, run it in a separate non-root worker container; never inside API request handlers. Do not commercialize LinkedIn scraping.
3. **Private object storage** — S3 in `ap-south-1` (Mumbai) with SSE-KMS and short-lived presigned uploads for resumes.
4. **Deploy** — single EC2 (or Compose) in Mumbai + RDS + Caddy TLS; Secrets Manager/SSM for keys; CloudWatch + Sentry.
5. **Google OAuth verification** — production consent screen for sensitive `gmail.send` before external users.
6. **React dashboard (optional)** — only if Jinja UX becomes a bottleneck; keep FastAPI as the API boundary.

## Explicit non-goals for early scale

- Kubernetes / microservices
- Celery + Redis until queue volume justifies them
- Selling LinkedIn scrape/automation as a product feature
- Fully autonomous apply without human approval as the default

## References

- LoopCV-style UX inspiration: https://www.loopcv.pro/
- Product MVP: [mvp.md](./mvp.md)
- Validation kit: [../validation/](../validation/)

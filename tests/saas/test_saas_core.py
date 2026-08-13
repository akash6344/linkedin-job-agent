"""SaaS unit tests: sources, entitlements, billing, privacy, matching."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path


class SaasTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        root = Path(self._tmpdir.name)
        db_path = root / "saas.db"
        os.environ["SAAS_DATABASE_URL"] = f"sqlite:///{db_path}"
        os.environ["SAAS_UPLOAD_DIR"] = str(root / "uploads")
        os.environ["SAAS_SECRET_KEY"] = "test-secret-key"
        os.environ["SAAS_FORCE_SQLITE"] = "1"
        os.environ.pop("MONGO_URI", None)
        # Force re-init
        import jobsearch_saas.db as dbmod
        import jobsearch_saas.config as cfg

        cfg.DATABASE_URL = os.environ["SAAS_DATABASE_URL"]
        cfg.UPLOAD_DIR = Path(os.environ["SAAS_UPLOAD_DIR"])
        cfg.MONGO_URI = ""
        cfg.FORCE_SQLITE = True
        dbmod._initialized = False
        dbmod.init_db()

    def tearDown(self) -> None:
        self._tmpdir.cleanup()


class TestSources(SaasTestCase):
    def test_linkedin_excluded(self) -> None:
        from jobsearch_saas.jobs.sources import assert_permitted, source_catalog

        with self.assertRaises(ValueError):
            assert_permitted("linkedin_scrape")
        catalog = {s["id"]: s for s in source_catalog()}
        self.assertEqual(catalog["linkedin_scrape"]["compliance"], "excluded")
        self.assertEqual(catalog["remotive"]["compliance"], "permitted")

    def test_user_paste_upsert(self) -> None:
        from jobsearch_saas.jobs.sources import parse_user_paste, upsert_job
        from jobsearch_saas import db

        job = parse_user_paste(
            title="Python Developer",
            company="Acme",
            description="Hiring in Bengaluru. Apply at jobs@acme.test",
            apply_email="jobs@acme.test",
        )
        job_id = upsert_job(job)
        with db.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        self.assertEqual(row["source"], "user_paste")
        self.assertEqual(row["apply_email"], "jobs@acme.test")


class TestAuthBillingPrivacy(SaasTestCase):
    def test_signup_consent_and_plan(self) -> None:
        from jobsearch_saas.auth import create_user, record_consent, list_consents
        from jobsearch_saas.entitlements import active_plan, grant_beta_pass
        from jobsearch_saas.billing.razorpay_billing import create_order, verify_and_activate, plan_price_breakdown
        from jobsearch_saas.privacy.controls import export_user_data, delete_user_account, latest_consent_map

        user = create_user(email="beta@example.com", password="password123", full_name="Beta User")
        record_consent(user["id"], purpose="job_matching", granted=True)
        record_consent(user["id"], purpose="email_sending", granted=False)
        consents = latest_consent_map(user["id"])
        self.assertTrue(consents["job_matching"])
        self.assertFalse(consents["email_sending"])
        self.assertTrue(list_consents(user["id"]))

        plan = active_plan(user["id"])
        self.assertEqual(plan["plan_id"], "free")
        self.assertEqual(plan["applications_per_month"], 3)

        grant_beta_pass(user["id"], days=30)
        plan = active_plan(user["id"])
        self.assertEqual(plan["plan_id"], "pass_249")
        self.assertTrue(plan.get("applications_unlimited"))

        breakdown = plan_price_breakdown("pass_199")
        self.assertGreater(breakdown["total_paise"], breakdown["base_paise"])
        self.assertEqual(breakdown["total_paise"], 19900)

        order = create_order(user["id"], "pass_199")
        self.assertTrue(order["dev_mode"])
        result = verify_and_activate(
            user_id=user["id"],
            payment_id=order["payment_id"],
            razorpay_order_id=order["order_id"],
            razorpay_payment_id="pay_test",
            razorpay_signature="dev_bypass",
        )
        self.assertEqual(result["entitlement"]["plan_id"], "pass_199")

        exported = export_user_data(user["id"])
        self.assertEqual(exported["user"]["email"], "beta@example.com")
        delete_user_account(user["id"])
        from jobsearch_saas.auth import get_user

        self.assertIsNone(get_user(user["id"]))

    def test_matching_and_draft_quota(self) -> None:
        from jobsearch_saas.auth import create_user
        from jobsearch_saas.jobs.matching import save_search_prefs, match_user_to_open_jobs, list_matches
        from jobsearch_saas.jobs.sources import parse_user_paste, upsert_job
        from jobsearch_saas.drafts import create_draft_for_match, list_drafts
        from jobsearch_saas.entitlements import grant_beta_pass
        from jobsearch_saas.profiles import update_profile

        user = create_user(email="match@example.com", password="password123", full_name="Match User")
        grant_beta_pass(user["id"])
        update_profile(user["id"], skills=["Python", "FastAPI"])
        save_search_prefs(
            user["id"],
            {
                "roles": ["Python Developer"],
                "locations": ["India", "Remote"],
                "max_years_experience": 3,
                "exclusions": [],
                "daily_application_limit": 10,
            },
        )
        upsert_job(
            parse_user_paste(
                title="Python Developer",
                company="RemoteCo",
                location="Remote India",
                description="Looking for Python and FastAPI engineer in India. Email hr@remoteco.test",
                apply_email="hr@remoteco.test",
            )
        )
        created = match_user_to_open_jobs(user["id"], limit=5)
        self.assertGreaterEqual(len(created), 1)
        matches = list_matches(user["id"])
        self.assertTrue(matches)
        draft = create_draft_for_match(user["id"], matches[0]["id"])
        self.assertEqual(draft["status"], "pending_approval")
        self.assertIn("Python Developer", draft["subject"])
        pending = list_drafts(user["id"])
        self.assertEqual(len(pending), 1)


class TestOAuthHelpers(SaasTestCase):
    def test_token_roundtrip(self) -> None:
        from jobsearch_saas.email.oauth import encrypt_token, decrypt_token

        enc = encrypt_token("access-token-value")
        self.assertNotEqual(enc, "access-token-value")
        self.assertEqual(decrypt_token(enc), "access-token-value")


if __name__ == "__main__":
    unittest.main()

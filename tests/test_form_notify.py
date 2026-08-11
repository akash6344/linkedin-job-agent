"""Tests for end-of-run digest notifications."""

import unittest
from unittest.mock import patch

from linkedin_agent.notify.service import (
    DigestItem,
    RunSummary,
    build_run_digest,
    notify_google_form,
    notify_pending_decision,
    notify_email_sent,
    send_run_summary,
)


class TestBuildRunDigest(unittest.TestCase):
    def test_digest_has_separate_sections_without_post_bodies(self):
        summary = RunSummary(
            started_at="2026-07-26T12:00:00+00:00",
            scraped=40,
            job_posts=10,
            emails_sent=1,
            forms_notified=1,
            pending=1,
            applied_items=[
                DigestItem(
                    kind="applied",
                    company="Acme",
                    job_title="Python Developer",
                    apply_email="hr@acme.com",
                    post_url="https://linkedin.com/posts/1",
                    keyword="Python developer hiring",
                )
            ],
            form_items=[
                DigestItem(
                    kind="form",
                    company="BotCo",
                    job_title="AI Engineer",
                    form_url="https://forms.gle/xyz",
                    post_url="https://linkedin.com/posts/2",
                )
            ],
            pending_items=[
                DigestItem(
                    kind="pending",
                    company="StartupX",
                    job_title="Backend Engineer",
                    reason="No email or Google Form found",
                    post_url="https://linkedin.com/posts/3",
                )
            ],
        )
        subject, body = build_run_digest(summary)
        self.assertIn("[Run Report]", subject)
        self.assertIn("APPLICATIONS SENT", body)
        self.assertIn("GOOGLE FORMS", body)
        self.assertIn("PENDING REVIEW", body)
        self.assertIn("Acme — Python Developer", body)
        self.assertIn("hr@acme.com", body)
        self.assertIn("https://forms.gle/xyz", body)
        self.assertIn("StartupX — Backend Engineer", body)
        self.assertNotIn("Feed post", body)
        self.assertNotIn("We're Hiring", body)

    def test_notify_queues_without_emailing(self):
        summary = RunSummary()
        with patch("linkedin_agent.notify.service.send_plain_email") as send_mail:
            notify_pending_decision(
                summary,
                {"keyword": "x", "url": "https://p/1", "company": "C", "job_title": "T"},
                "No email or Google Form found",
                company="C",
                job_title="T",
            )
            notify_google_form(
                summary,
                {"keyword": "y", "url": "https://p/2"},
                "https://forms.gle/a",
                company="FCo",
                job_title="AI",
            )
            notify_email_sent(
                summary,
                {"keyword": "z", "url": "https://p/3"},
                "hr@z.com",
                "subj",
                "ai_engineer",
                company="ZCo",
                job_title="AI Eng",
            )
        send_mail.assert_not_called()
        self.assertEqual(len(summary.pending_items), 1)
        self.assertEqual(len(summary.form_items), 1)
        self.assertEqual(len(summary.applied_items), 1)

    def test_send_run_summary_emails_one_digest(self):
        summary = RunSummary(
            emails_sent=0,
            forms_notified=1,
            pending=1,
            form_items=[
                DigestItem(kind="form", company="A", job_title="B", form_url="https://forms.gle/1")
            ],
            pending_items=[
                DigestItem(kind="pending", company="C", job_title="D", reason="No email")
            ],
        )
        with (
            patch("linkedin_agent.notify.service.send_plain_email") as send_mail,
            patch("linkedin_agent.notify.service.send_telegram", return_value=True),
            patch("linkedin_agent.notify.service._macos_banner"),
            patch(
                "linkedin_agent.notify.service.FORM_NOTIFY_EMAIL",
                "uppalaakash2004@gmail.com",
            ),
        ):
            send_run_summary(summary)
        send_mail.assert_called_once()
        to, subject, body = send_mail.call_args[0]
        self.assertEqual(to, "uppalaakash2004@gmail.com")
        self.assertIn("[Run Report]", subject)
        self.assertIn("GOOGLE FORMS", body)
        self.assertIn("PENDING REVIEW", body)

    def test_empty_run_skips_digest_email(self):
        summary = RunSummary(scraped=20, job_posts=0, emails_sent=0, forms_notified=0, pending=0)
        with (
            patch("linkedin_agent.notify.service.send_plain_email") as send_mail,
            patch("linkedin_agent.notify.service.send_telegram", return_value=True),
            patch("linkedin_agent.notify.service._macos_banner"),
        ):
            send_run_summary(summary)
        send_mail.assert_not_called()

    def test_error_run_emails_digest(self):
        summary = RunSummary(error="browser crashed", emails_sent=0, forms_notified=0, pending=0)
        with (
            patch("linkedin_agent.notify.service.send_plain_email") as send_mail,
            patch("linkedin_agent.notify.service.send_telegram", return_value=True),
            patch("linkedin_agent.notify.service._macos_banner"),
            patch(
                "linkedin_agent.notify.service.FORM_NOTIFY_EMAIL",
                "uppalaakash2004@gmail.com",
            ),
        ):
            send_run_summary(summary)
        send_mail.assert_called_once()
        subject, body = send_mail.call_args[0][1], send_mail.call_args[0][2]
        self.assertIn("[Run Report]", subject)
        self.assertIn("browser crashed", body)


if __name__ == "__main__":
    unittest.main()

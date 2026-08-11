"""Tests for email template placeholder filling."""

import unittest
from unittest.mock import patch

from linkedin_agent.apply.email_sender import draft_email, fill_template


class TestFillTemplate(unittest.TestCase):
    def test_replaces_role(self):
        text = "apply for the {role} role at {company}"
        self.assertEqual(
            fill_template(text, role="Python Developer", company="Acme"),
            "apply for the Python Developer role at Acme",
        )

    def test_replaces_title_alias(self):
        self.assertEqual(
            fill_template("the {title} opening", role="Backend Engineer"),
            "the Backend Engineer opening",
        )


class TestDraftEmailPlaceholders(unittest.TestCase):
    def test_fallback_fills_role_when_ollama_fails(self):
        with patch("linkedin_agent.apply.email_sender.ollama.chat", side_effect=RuntimeError("down")):
            subject, body = draft_email(
                {"keyword": "Python Developer", "post_text": "Hiring Python Developer"},
                {"job_title": "Python Developer", "company": "Acme"},
                "python_software",
                "python_software",
            )
        self.assertNotIn("{role}", body)
        self.assertIn("Python Developer", body)
        self.assertIn("Python Developer", subject)

    def test_scrubs_role_placeholder_from_llm_body(self):
        fake = {
            "message": {
                "content": '{"subject": "Hi", "body": "I saw the {role} role and want to apply."}'
            }
        }
        with patch("linkedin_agent.apply.email_sender.ollama.chat", return_value=fake):
            _, body = draft_email(
                {"keyword": "AI Engineer", "post_text": "Hiring AI Engineer"},
                {"job_title": "AI Engineer", "company": "BotCo"},
                "ai_engineer",
                "ai_engineer",
            )
        self.assertNotIn("{role}", body)
        self.assertIn("AI Engineer", body)


if __name__ == "__main__":
    unittest.main()

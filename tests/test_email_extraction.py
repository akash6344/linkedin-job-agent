"""Unit tests for apply-email extraction / normalization."""

import unittest

from linkedin_agent.llm.analyzer import (
    extract_emails,
    is_valid_apply_email,
    normalize_apply_email,
)


class TestIsValidApplyEmail(unittest.TestCase):
    def test_accepts_simple_address(self):
        self.assertTrue(is_valid_apply_email("hr@company.com"))

    def test_rejects_prose(self):
        self.assertFalse(is_valid_apply_email("DM the HR team"))
        self.assertFalse(is_valid_apply_email("Comment your email ID"))
        self.assertFalse(is_valid_apply_email("Sarah McLennan"))

    def test_rejects_multi_and_url(self):
        self.assertFalse(is_valid_apply_email("a@x.com, b@y.com"))
        self.assertFalse(is_valid_apply_email("https://lnkd.in/abc"))
        self.assertFalse(is_valid_apply_email("[a@x.com]"))

    def test_rejects_empty(self):
        self.assertFalse(is_valid_apply_email(""))
        self.assertFalse(is_valid_apply_email(None))


class TestNormalizeApplyEmail(unittest.TestCase):
    def test_rejects_llm_prose_when_post_has_no_email(self):
        post = "Comment your email ID – our team will share the assignment link."
        self.assertEqual(normalize_apply_email(post, "Comment your email ID"), "")
        self.assertEqual(normalize_apply_email(post, "DM the HR team"), "")

    def test_rejects_llm_name_and_url(self):
        post = "We're hiring. DM us for details."
        self.assertEqual(normalize_apply_email(post, "Sarah McLennan"), "")
        self.assertEqual(normalize_apply_email(post, "https://lnkd.in/xyz"), "")

    def test_extracts_single_email_from_post(self):
        post = "Apply at hr@acme.com with your resume."
        self.assertEqual(normalize_apply_email(post, ""), "hr@acme.com")
        self.assertEqual(normalize_apply_email(post, None), "hr@acme.com")

    def test_accepts_llm_when_it_matches_post(self):
        post = "Send CV to jobs@acme.com"
        self.assertEqual(normalize_apply_email(post, "jobs@acme.com"), "jobs@acme.com")

    def test_ignores_llm_email_not_in_post(self):
        # Model must not invent addresses that are not in the post.
        post = "Apply via hr@real.com only."
        self.assertEqual(
            normalize_apply_email(post, "fake@invented.com"),
            "hr@real.com",
        )

    def test_splits_multi_email_llm_string(self):
        post = (
            "Mail talent@hitasolutions.com or ta1@stride4e.com for the role."
        )
        self.assertEqual(
            normalize_apply_email(post, "talent@hitasolutions.com, ta1@stride4e.com"),
            "talent@hitasolutions.com",
        )

    def test_bracketed_list(self):
        post = "Contact [rajasekaran1955@gmail.com, srivatchan444@gmail.com]"
        result = normalize_apply_email(
            post, "[rajasekaran1955@gmail.com, srivatchan444@gmail.com]"
        )
        self.assertIn(result, {"rajasekaran1955@gmail.com", "srivatchan444@gmail.com"})

    def test_prefers_hiring_inbox(self):
        post = "Reach john.doe@acme.com or careers@acme.com"
        self.assertEqual(normalize_apply_email(post, ""), "careers@acme.com")

    def test_strips_mixed_prose_keeping_real_email(self):
        post = (
            "enquiry@techlinker.asia or reach out to Carrie Lui for details"
        )
        self.assertEqual(
            normalize_apply_email(
                post, "enquiry@techlinker.asia or reach out to Carrie Lui"
            ),
            "enquiry@techlinker.asia",
        )

    def test_pipe_and_slash_separators(self):
        post = "a@x.com | b@y.com / jobs@z.com"
        self.assertEqual(
            normalize_apply_email(post, "a@x.com | b@y.com / jobs@z.com"),
            "jobs@z.com",
        )

    def test_accepts_llm_list_of_emails(self):
        post = "Apply at hr@acme.com or jobs@acme.com"
        self.assertEqual(
            normalize_apply_email(post, ["hr@acme.com", "jobs@acme.com"]),
            "hr@acme.com",
        )


class TestExtractEmails(unittest.TestCase):
    def test_dedupes_case_insensitive(self):
        self.assertEqual(
            extract_emails("HR@Acme.com and hr@acme.com"),
            ["HR@Acme.com"],
        )

    def test_handles_list_input(self):
        self.assertEqual(
            extract_emails(["hr@acme.com", "not-an-email"]),
            ["hr@acme.com"],
        )


if __name__ == "__main__":
    unittest.main()

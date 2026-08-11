"""Tests for deterministic role-fit filtering and title cleanup."""

import unittest

from linkedin_agent.llm.role_filter import meets_role_requirement, sanitize_job_title


class TestSanitizeJobTitle(unittest.TestCase):
    def test_keeps_single_title_from_multi_role_list(self):
        title = (
            "Full Stack Developers, AI/ML Engineers, Mobile App Developers, "
            "UI/UX Designers, Business Development Executives"
        )
        self.assertEqual(sanitize_job_title(title), "Full Stack Developers")

    def test_falls_back_to_keyword(self):
        self.assertEqual(
            sanitize_job_title("", "Python developer hiring"),
            "Python developer",
        )

    def test_handles_llm_list_of_titles(self):
        self.assertEqual(
            sanitize_job_title(["AI Engineer", "Prompt Engineer", "Data Scientist"], prefer_ai=True),
            "AI Engineer",
        )


class TestRoleRequirement(unittest.TestCase):
    def test_rejects_sales_title(self):
        ok, reason = meets_role_requirement(
            "We are hiring immediately.",
            {"job_title": "Sales Engineer"},
            "software_engineer",
        )
        self.assertFalse(ok)
        self.assertIn("non-tech title", reason)

    def test_rejects_training_role_for_ai(self):
        ok, reason = meets_role_requirement(
            "Hiring AI trainer for campus program.",
            {"job_title": "AI Trainer"},
            "ai_engineer",
        )
        self.assertFalse(ok)
        self.assertTrue("non-tech" in reason or "teaching" in reason)

    def test_rejects_ai_filmmaker_content(self):
        ok, reason = meets_role_requirement(
            "Hiring AI Filmmakers and AI Video Creators.",
            {"job_title": "AI Filmmakers"},
            "generative_ai",
        )
        self.assertFalse(ok)

    def test_rejects_data_science_trainer(self):
        ok, reason = meets_role_requirement(
            "Join PrepCheck Academy as Agentic AI Trainer.",
            {"job_title": "Agentic AI Trainer"},
            "generative_ai",
        )
        self.assertFalse(ok)

    def test_rejects_ai_keyword_but_hardware_role(self):
        ok, reason = meets_role_requirement(
            "We mention AI once. Hiring Hardware Engineer.",
            {"job_title": "Hardware Engineer"},
            "ai_engineer",
        )
        self.assertFalse(ok)

    def test_accepts_core_ai_engineer(self):
        ok, _ = meets_role_requirement(
            "Looking for AI Engineer with LangChain and RAG experience.",
            {"job_title": "AI Engineer"},
            "ai_engineer",
        )
        self.assertTrue(ok)

    def test_prefers_ai_title_from_multi_role_list(self):
        title = (
            "Full Stack Developers, AI/ML Engineers, Mobile App Developers, "
            "UI/UX Designers, Business Development Executives"
        )
        self.assertEqual(
            sanitize_job_title(title, prefer_ai=True),
            "AI/ML Engineers",
        )

    def test_rejects_role_mismatch(self):
        ok, reason = meets_role_requirement(
            "Need a UI designer with Figma experience.",
            {"job_title": "UI Designer"},
            "python_developer",
        )
        self.assertFalse(ok)
        self.assertIn("mismatch", reason.lower())

    def test_accepts_matching_role(self):
        ok, _ = meets_role_requirement(
            "Hiring backend Python developer with FastAPI experience.",
            {"job_title": "Backend Python Developer"},
            "backend_developer",
        )
        self.assertTrue(ok)

    def test_accepts_fullstack_role(self):
        ok, _ = meets_role_requirement(
            "Hiring Full Stack Developer with React and Node.",
            {"job_title": "Full Stack Developer"},
            "fullstack_developer",
        )
        self.assertTrue(ok)

    def test_accepts_mern_as_fullstack(self):
        ok, _ = meets_role_requirement(
            "Looking for MERN Stack Developer.",
            {"job_title": "MERN Stack Developer"},
            "fullstack_developer",
        )
        self.assertTrue(ok)

    def test_prefers_fullstack_title_from_multi_role_list(self):
        title = "Sales Executive, Full Stack Developer, Content Writer"
        self.assertEqual(
            sanitize_job_title(title, prefer_fullstack=True),
            "Full Stack Developer",
        )

    def test_software_search_accepts_fullstack_title(self):
        ok, _ = meets_role_requirement(
            "We are hiring a Full Stack Engineer.",
            {"job_title": "Full Stack Engineer"},
            "software_engineer",
        )
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()

"""Tests for image OCR enrichment helpers."""

import unittest
from unittest.mock import patch

from linkedin_agent.llm.image_text import (
    merge_image_text,
    needs_image_enrichment,
)


class TestNeedsImageEnrichment(unittest.TestCase):
    def test_true_when_no_apply_contact(self):
        self.assertTrue(
            needs_image_enrichment(
                "Hiring Python developer",
                {"apply_email": "", "google_form_url": "", "min_years_experience": 2},
            )
        )

    def test_true_when_experience_unknown(self):
        self.assertTrue(
            needs_image_enrichment(
                "Hiring",
                {
                    "apply_email": "hr@x.com",
                    "google_form_url": "",
                    "min_years_experience": None,
                    "experience_requirement": None,
                },
            )
        )

    def test_false_when_contact_and_exp_known(self):
        self.assertFalse(
            needs_image_enrichment(
                "Hiring",
                {
                    "apply_email": "hr@x.com",
                    "google_form_url": "",
                    "min_years_experience": 2,
                },
            )
        )


class TestMergeImageText(unittest.TestCase):
    def test_appends_ocr_block(self):
        merged = merge_image_text("Post body", "5+ years\nhr@acme.com")
        self.assertIn("Post body", merged)
        self.assertIn("5+ years", merged)
        self.assertIn("Text extracted from post image", merged)

    def test_empty_ocr_unchanged(self):
        self.assertEqual(merge_image_text("only text", "  "), "only text")


class TestExtractUsesTesseract(unittest.TestCase):
    def test_extract_text_from_bytes_calls_tesseract(self):
        from linkedin_agent.llm.image_text import extract_text_from_image_bytes

        png = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
            b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05"
            b"\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        with patch(
            "linkedin_agent.llm.image_text._ocr_tesseract",
            return_value="Experience: 5+ years\nEmail: jobs@acme.com",
        ), patch(
            "linkedin_agent.llm.image_text._ocr_ollama_vision",
            return_value="",
        ):
            text = extract_text_from_image_bytes(png)
        self.assertIn("5+ years", text)
        self.assertIn("jobs@acme.com", text)


if __name__ == "__main__":
    unittest.main()

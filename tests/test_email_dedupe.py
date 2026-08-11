"""Tests for apply-email dedupe."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from linkedin_agent.storage import db as db_mod


class TestAlreadyAppliedEmail(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "test.db"
        self._patchers = [
            patch.object(db_mod, "DB_PATH", self.db_path),
            patch.object(db_mod, "DATA_DIR", Path(self._tmpdir.name)),
            patch.object(db_mod, "_db_initialized", False),
        ]
        for p in self._patchers:
            p.start()
        db_mod.init_db()

    def tearDown(self):
        for p in self._patchers:
            p.stop()
        self._tmpdir.cleanup()

    def test_detects_prior_applied_case_insensitive(self):
        db_mod.save_post(
            {
                "url": "https://example.com/1",
                "role_tag": "python_developer",
                "keyword": "Python developer hiring",
                "status": "applied",
                "apply_method": "email",
                "apply_email": "kamran@adescaretech.com",
                "company": "Adescare",
                "job_title": "Python Developer",
            }
        )
        prior = db_mod.already_applied_email("Kamran@Adescaretech.com")
        self.assertIsNotNone(prior)
        self.assertEqual(prior["company"], "Adescare")

    def test_ignores_non_applied_statuses(self):
        db_mod.save_post(
            {
                "url": "https://example.com/2",
                "role_tag": "python_developer",
                "keyword": "Python developer hiring",
                "status": "failed",
                "apply_method": "email",
                "apply_email": "hr@x.com",
            }
        )
        self.assertIsNone(db_mod.already_applied_email("hr@x.com"))


if __name__ == "__main__":
    unittest.main()

"""Tests for LinkedIn post permalink canonicalization."""

import unittest

from linkedin_agent.links import browse_link, canonical_post_url, is_synthetic_post_url
from linkedin_agent.notify.service import DigestItem, RunSummary, _item_from_post, build_run_digest


class TestCanonicalPostUrl(unittest.TestCase):
    def test_keeps_feed_update_share(self):
        url = "https://www.linkedin.com/feed/update/urn:li:share:7493169383154798593/"
        self.assertEqual(canonical_post_url(url), url)

    def test_rejects_company_posts_listing(self):
        url = "https://www.linkedin.com/company/ivabus/posts/"
        self.assertEqual(canonical_post_url(url), "")
        self.assertTrue(is_synthetic_post_url(url))

    def test_converts_posts_activity_slug(self):
        url = "https://www.linkedin.com/posts/primisafe-technologies_activity-7493169383154798593-AbCd"
        self.assertEqual(
            canonical_post_url(url),
            "https://www.linkedin.com/feed/update/urn:li:activity:7493169383154798593/",
        )

    def test_strips_utm_from_clipboard_feed_url(self):
        raw = "https://www.linkedin.com/feed/update/urn:li:activity:7493169383154798593/?utm_source=share&utm_medium=member_desktop"
        self.assertEqual(
            canonical_post_url(raw),
            "https://www.linkedin.com/feed/update/urn:li:activity:7493169383154798593/",
        )
        url = "https://www.linkedin.com/search/results/companies/?keywords=Gartner"
        self.assertEqual(canonical_post_url(url), "")
        post = {"url": "https://linkedin.local/post/x/abc", "company": "Gartner"}
        link = browse_link(post, company="Gartner")
        self.assertIn("keywords=Gartner", link)


class TestDigestAlwaysLabelsPost(unittest.TestCase):
    def test_applied_row_uses_post_label(self):
        item = _item_from_post(
            kind="applied",
            post={"url": "https://www.linkedin.com/feed/update/urn:li:share:1/", "keyword": "x"},
            company="Acme",
            job_title="Engineer",
            apply_email="hr@acme.com",
        )
        summary = RunSummary(applied_items=[item], emails_sent=1)
        _, body = build_run_digest(summary)
        self.assertIn("Post: https://www.linkedin.com/feed/update/urn:li:share:1/", body)
        self.assertNotIn("Post: https://www.linkedin.com/company/", body)

    def test_company_listing_is_not_shown_as_post(self):
        item = _item_from_post(
            kind="applied",
            post={
                "url": "https://www.linkedin.com/company/ivabus/posts/",
                "company_url": "https://www.linkedin.com/company/ivabus",
                "keyword": "Full stack developer hiring",
            },
            company="ivabus",
            job_title="Full-Stack Developer",
            apply_email="build@ivabus.com",
        )
        self.assertEqual(item.post_url, "")
        summary = RunSummary(applied_items=[item], emails_sent=1)
        _, body = build_run_digest(summary)
        self.assertNotIn("Post: https://www.linkedin.com/company/ivabus/posts/", body)
        self.assertIn("Company: https://www.linkedin.com/company/ivabus", body)


if __name__ == "__main__":
    unittest.main()

"""Helpers for browseable post / company links in digests and records."""

from __future__ import annotations

import re
import urllib.parse
from typing import Any

_COMPANY_URL_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/company/[A-Za-z0-9\-_%]+/?",
    re.I,
)
_LOCAL_POST_RE = re.compile(r"^https?://linkedin\.local/", re.I)
_FEED_UPDATE_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/feed/update/(urn:li:(?:activity|ugcPost|share):\d+)/?",
    re.I,
)
_POSTS_ACTIVITY_RE = re.compile(
    r"https?://(?:www\.)?linkedin\.com/posts/[^/?#]*activity-(\d+)",
    re.I,
)
_URN_RE = re.compile(r"urn:li:(activity|ugcPost|share):(\d+)", re.I)
_COMPANY_POSTS_RE = re.compile(
    r"linkedin\.com/company/[^/]+/posts/?$",
    re.I,
)


def extract_company_url_from_text(text: str) -> str:
    if not text:
        return ""
    m = _COMPANY_URL_RE.search(text)
    if not m:
        return ""
    return m.group(0).rstrip("/")


def company_search_url(company: str) -> str:
    name = (company or "").strip()
    if not name or name.lower() in {"your company", "-", "unknown"}:
        return ""
    q = urllib.parse.quote(name)
    return f"https://www.linkedin.com/search/results/companies/?keywords={q}"


def canonical_post_url(url: str | None) -> str:
    """Normalize to a clickable /feed/update/ permalink, or '' if not a real post."""
    u = (url or "").strip().split("?")[0].split("#")[0]
    if not u:
        return ""
    if _LOCAL_POST_RE.match(u) or _COMPANY_POSTS_RE.search(u):
        return ""
    if "/search/results/" in u.lower():
        return ""
    feed = _FEED_UPDATE_RE.search(u)
    if feed:
        return f"https://www.linkedin.com/feed/update/{feed.group(1)}/"
    activity = _POSTS_ACTIVITY_RE.search(u)
    if activity:
        return f"https://www.linkedin.com/feed/update/urn:li:activity:{activity.group(1)}/"
    urn = _URN_RE.search(u)
    if urn and "linkedin.com" in u.lower():
        return f"https://www.linkedin.com/feed/update/urn:li:{urn.group(1)}:{urn.group(2)}/"
    return ""


def is_real_linkedin_post_url(url: str | None) -> bool:
    return bool(canonical_post_url(url))


def is_synthetic_post_url(url: str | None) -> bool:
    u = (url or "").strip()
    if not u:
        return True
    if _LOCAL_POST_RE.match(u):
        return True
    if u.endswith("#post"):
        return True
    if _COMPANY_POSTS_RE.search(u):
        return True
    if "results/companies" in u.lower():
        return True
    return not is_real_linkedin_post_url(u)


def enrich_company_url(post: dict[str, Any], *, company: str = "") -> str:
    """Best available company LinkedIn URL from post fields / text."""
    existing = (post.get("company_url") or "").strip()
    if existing and "linkedin.com/company/" in existing.lower():
        return existing.rstrip("/")
    from_text = extract_company_url_from_text(post.get("post_text") or "")
    if from_text:
        return from_text
    return company_search_url(company or post.get("company") or "")


def browse_link(post: dict[str, Any], *, company: str = "") -> str:
    """Prefer real post permalink; else company page / company search."""
    permalink = canonical_post_url(post.get("url"))
    if permalink:
        return permalink
    company_url = enrich_company_url(post, company=company)
    if company_url:
        return company_url
    return (post.get("url") or "").strip()

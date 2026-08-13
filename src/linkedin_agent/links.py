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


def is_synthetic_post_url(url: str | None) -> bool:
    u = (url or "").strip()
    if not u:
        return True
    if _LOCAL_POST_RE.match(u):
        return True
    if u.endswith("#post"):
        return True
    return False


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
    """Prefer real post URL; else company page / company search."""
    url = (post.get("url") or "").strip()
    if url and not is_synthetic_post_url(url):
        return url
    company_url = enrich_company_url(post, company=company)
    if company_url:
        return company_url
    return ""

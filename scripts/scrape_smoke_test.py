#!/usr/bin/env python3
"""Quick Chrome scrape smoke test: one keyword, Top match + Latest."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from linkedin_agent.browser.session import (  # noqa: E402
    create_browser_context,
    ensure_logged_in,
    get_live_page,
    stop_chrome_hide_loop,
)
from linkedin_agent.config import SCROLL_COUNT  # noqa: E402
from linkedin_agent.scrape.service import search_role  # noqa: E402


async def main() -> int:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "Software Engineer hiring"
    role = {
        "keyword": keyword,
        "role_tag": "smoke_test",
        "resume_key": "python_software",
        "email_template": "python_software",
    }
    print(f"SCROLL_COUNT={SCROLL_COUNT} (≈{max(6, SCROLL_COUNT // 2)} scrolls per sort)")
    print(f"Keyword: {keyword}")
    print("Opening Chrome (visible) for smoke test...")

    playwright, context = await create_browser_context(
        headless=False, mode="visible", hide_chrome=False
    )
    page = None
    try:
        page = await get_live_page(context, None)
        await ensure_logged_in(page, interactive=False)
        posts = await search_role(page, role)
        print("\n=== SMOKE RESULT ===")
        print(f"total_posts={len(posts)}")
        for i, p in enumerate(posts[:12], 1):
            author = (p.get("author") or "")[:40]
            text = (p.get("post_text") or "").replace("\n", " ")[:90]
            print(f"{i:02d}. {author} | {text}")
        out = ROOT / "logs" / "scrape_smoke_result.json"
        out.write_text(json.dumps({"keyword": keyword, "count": len(posts), "posts": posts[:30]}, indent=2), encoding="utf-8")
        print(f"Wrote {out}")
        return 0 if posts else 1
    finally:
        await stop_chrome_hide_loop()
        await context.close()
        await playwright.stop()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

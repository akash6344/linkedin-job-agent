"""Scrape LinkedIn content search — one keyword per run, Posts + Latest + Past 24 hours."""

import asyncio
import hashlib
import urllib.parse
from typing import Any

from playwright.async_api import BrowserContext, Page

from linkedin_agent.browser.session import (
    click_filter_button,
    ensure_logged_in,
    get_live_page,
    safe_goto,
)
from linkedin_agent.config import (
    LOGS_DIR,
    MAX_POSTS_PER_SEARCH,
    PAGE_LOAD_DELAY_SEC,
    SCROLL_COUNT,
    SEARCH_ROLES,
)

# LinkedIn content search often hides /feed/update/ links — extract from result cards + text
EXTRACT_POSTS_JS = """() => {
    const items = [];
    const seen = new Set();

    function isNavBlob(text) {
        return text.includes('Skip to search')
            || text.includes('Get hired for')
            || text.includes('Try Premium for')
            || text.startsWith('Home\\nMy Network');
    }

    function pickAuthor(text, el) {
        const fromEl = el.querySelector(
            '.update-components-actor__title, .entity-result__title-text, a[href*="/in/"] span[aria-hidden="true"]'
        );
        if (fromEl?.innerText?.trim()) return fromEl.innerText.trim();

        const m = text.match(/^Feed post\\s*\\n?([^\\n•]+)/i)
            || text.match(/^([^\\n•]{2,60})\\s*•\\s*(1st|2nd|3rd|\\+|Verified)/i);
        return m ? m[1].trim() : '';
    }

    function pickUrl(el, text) {
        for (const link of el.querySelectorAll('a[href]')) {
            const href = (link.href || '').split('?')[0];
            if (href.includes('/feed/update/') || href.includes('/posts/') || href.includes('activity-')) {
                return href;
            }
        }
        const urnEl = el.closest('[data-urn]') || el.querySelector('[data-urn]') || el;
        const urn = urnEl.getAttribute?.('data-urn') || '';
        if (urn.includes('activity') || urn.includes('ugcPost')) {
            const id = urn.split(':').pop();
            return `https://www.linkedin.com/feed/update/urn:li:activity:${id}/`;
        }
        const profile = el.querySelector('a[href*="/in/"]');
        if (profile?.href) {
            return profile.href.split('?')[0] + '#post';
        }
        return '';
    }

    function addFromElement(el) {
        const text = (el.innerText || '').trim();
        if (text.length < 80 || isNavBlob(text)) return;

        const url = pickUrl(el, text);
        const key = url || text.slice(0, 200);
        if (seen.has(key)) return;
        seen.add(key);

        items.push({
            url,
            author: pickAuthor(text, el),
            post_text: text.slice(0, 8000),
        });
    }

    const selectors = [
        '[data-chameleon-result-urn]',
        'li.reusable-search__result-container',
        '.feed-shared-update-v2',
        'div[data-urn*="urn:li:activity"]',
        'div[data-urn*="urn:li:ugcPost"]',
        'main li',
        'main div[data-urn]',
    ];

    for (const sel of selectors) {
        document.querySelectorAll(sel).forEach(el => {
            const text = (el.innerText || '').trim();
            if (text.length < 80) return;
            const looksLikePost = text.includes('Feed post')
                || /\\b(hiring|hire|opening|vacancy|apply|walk-?in|job)\\b/i.test(text);
            if (looksLikePost || sel.includes('chameleon') || sel.includes('reusable-search')) {
                addFromElement(el);
            }
        });
    }

    for (const link of document.querySelectorAll(
        'a[href*="/feed/update/"], a[href*="/posts/"], a[href*="activity-"]'
    )) {
        let box = link.closest('[data-chameleon-result-urn], li, div[data-urn]');
        if (!box) {
            let p = link.parentElement;
            for (let i = 0; i < 10 && p; i++) {
                if ((p.innerText || '').length > 100) { box = p; break; }
                p = p.parentElement;
            }
        }
        if (box) addFromElement(box);
    }

    return items;
}"""


def build_search_url(keyword: str) -> str:
    params = {
        "keywords": keyword,
        "origin": "FACETED_SEARCH",
        "sortBy": "date_posted",
        "datePosted": "past-24h",
    }
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"https://www.linkedin.com/search/results/content/?{query}"


def _stable_url(item: dict[str, Any], keyword: str) -> str:
    url = (item.get("url") or "").strip()
    if url and not url.endswith("#post"):
        return url
    digest = hashlib.sha256(
        f"{keyword}|{item.get('author', '')}|{item.get('post_text', '')[:500]}".encode("utf-8")
    ).hexdigest()[:16]
    slug = keyword.lower().replace(" ", "-")
    return f"https://linkedin.local/post/{slug}/{digest}"


async def _scroll_results(page: Page, passes: int) -> None:
    """Scroll to load paginated search results."""
    print(f"  Scrolling {passes}x to load more posts...")
    for i in range(passes):
        await page.evaluate(
            """() => {
                const main = document.querySelector('main') || document.body;
                main.scrollTop = main.scrollHeight;
                window.scrollTo(0, document.body.scrollHeight);
            }"""
        )
        await page.wait_for_timeout(2200)
        count = await page.evaluate(
            """() => document.querySelectorAll('[data-chameleon-result-urn], li.reusable-search__result-container, .feed-shared-update-v2').length"""
        )
        print(f"    scroll {i + 1}/{passes} — {count} result nodes visible")


async def _wait_for_results(page: Page) -> None:
    try:
        await page.wait_for_function(
            """() => {
                const n = document.querySelectorAll(
                    '[data-chameleon-result-urn], li.reusable-search__result-container, .feed-shared-update-v2'
                ).length;
                const body = document.body?.innerText || '';
                return n > 0 || body.includes('Feed post');
            }""",
            timeout=30000,
        )
    except Exception:
        await page.wait_for_timeout(5000)


async def _apply_search_filters(page: Page) -> None:
    for label in ("Posts", "Post"):
        if await click_filter_button(page, label):
            break
    for label in ("Latest", "Date posted"):
        await click_filter_button(page, label)
    for label in ("Past 24 hours", "Past 24 Hours", "Past 24h", "24 hours"):
        if await click_filter_button(page, label):
            break


async def _debug_page_state(page: Page, keyword: str) -> None:
    stats = await page.evaluate(
        """() => ({
            links: document.querySelectorAll('a[href*="/feed/update/"], a[href*="/posts/"]').length,
            chameleon: document.querySelectorAll('[data-chameleon-result-urn]').length,
            results: document.querySelectorAll('li.reusable-search__result-container').length,
            feedPosts: (document.body?.innerText || '').includes('Feed post'),
            title: document.title,
            snippet: (document.body?.innerText || '').slice(0, 320).replace(/\\s+/g, ' '),
        })"""
    )
    print(
        f"  Debug [{keyword}]: chameleon={stats.get('chameleon')} "
        f"results={stats.get('results')} feed_post_text={stats.get('feedPosts')} "
        f"post_links={stats.get('links')}"
    )
    print(f"  Snippet: {stats.get('snippet')!r}")

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = keyword.lower().replace(" ", "_")
    shot = LOGS_DIR / f"debug_{safe_name}.png"
    try:
        await page.screenshot(path=str(shot), full_page=False)
        print(f"  Screenshot: {shot}")
    except Exception:
        pass


def _merge_batch(
    batch: list[dict[str, Any]],
    keyword: str,
    role_tag: str,
    posts: list[dict[str, Any]],
    seen_urls: set[str],
) -> None:
    for item in batch:
        url = _stable_url(item, keyword)
        if url in seen_urls:
            continue
        seen_urls.add(url)
        posts.append(
            {
                "url": url,
                "author": item.get("author", ""),
                "post_text": item.get("post_text", ""),
                "keyword": keyword,
                "role_tag": role_tag,
            }
        )


async def _extract_posts_from_page(page: Page, keyword: str, role_tag: str) -> list[dict[str, Any]]:
    posts: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    batch = await page.evaluate(EXTRACT_POSTS_JS)
    if not batch:
        await _debug_page_state(page, keyword)
    _merge_batch(batch or [], keyword, role_tag, posts, seen_urls)
    return posts[:MAX_POSTS_PER_SEARCH]


async def search_role(page: Page, role: dict[str, str]) -> list[dict[str, Any]]:
    keyword = role["keyword"]
    role_tag = role["role_tag"]
    url = build_search_url(keyword)

    print(f"\n  Searching: {keyword}")
    await safe_goto(page, url)
    await _apply_search_filters(page)
    await _wait_for_results(page)

    # Extract during scroll — LinkedIn virtualizes the DOM, so end-only extract misses posts.
    posts: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    _merge_batch(await page.evaluate(EXTRACT_POSTS_JS) or [], keyword, role_tag, posts, seen_urls)

    print(f"  Scrolling {SCROLL_COUNT}x to load more posts...")
    for i in range(SCROLL_COUNT):
        if len(posts) >= MAX_POSTS_PER_SEARCH:
            break
        await page.evaluate(
            """() => {
                const main = document.querySelector('main') || document.body;
                main.scrollTop = main.scrollHeight;
                window.scrollTo(0, document.body.scrollHeight);
            }"""
        )
        await page.wait_for_timeout(2200)
        _merge_batch(await page.evaluate(EXTRACT_POSTS_JS) or [], keyword, role_tag, posts, seen_urls)
        print(f"    scroll {i + 1}/{SCROLL_COUNT} — {len(posts)} unique posts so far")

    posts = posts[:MAX_POSTS_PER_SEARCH]
    if not posts:
        await _debug_page_state(page, keyword)
    print(f"  Found {len(posts)} posts")
    return posts


async def scrape_all_roles(context: BrowserContext, page: Page) -> list[dict[str, Any]]:
    all_posts: list[dict[str, Any]] = []
    seen: set[str] = set()

    for i, role in enumerate(SEARCH_ROLES):
        page = await get_live_page(context, page)
        try:
            posts = await search_role(page, role)
        except Exception as exc:
            print(f"  ✗ Search failed for {role['keyword']}: {exc}")
            posts = []

        for post in posts:
            if post["url"] not in seen:
                seen.add(post["url"])
                all_posts.append(post)

        if i < len(SEARCH_ROLES) - 1:
            from linkedin_agent.config import SEARCH_DELAY_SEC

            delay = min(SEARCH_DELAY_SEC, 20)
            print(f"  Waiting {delay}s before next search...")
            await asyncio.sleep(delay)
            page = await get_live_page(context, page)

    return all_posts


async def _scrape_once(mode: str | None) -> list[dict[str, Any]]:
    from linkedin_agent.browser.session import (
        create_browser_context,
        resolve_browser_mode,
        stop_chrome_hide_loop,
    )

    _, _, label = resolve_browser_mode(mode)
    print(f"\n  Scraper mode: {label}")

    playwright, context = await create_browser_context(mode=mode)
    page: Page | None = None
    try:
        page = await get_live_page(context, None)
        await ensure_logged_in(page, interactive=False)
        return await scrape_all_roles(context, page)
    finally:
        await stop_chrome_hide_loop()
        await context.close()
        await playwright.stop()


async def scrape_with_browser(*, mode: str | None = None) -> list[dict[str, Any]]:
    from linkedin_agent.config import BROWSER_MODE

    mode = mode or BROWSER_MODE
    posts = await _scrape_once(mode)

    if not posts and mode == "headless":
        print("\n  Headless returned 0 posts (LinkedIn likely blocked it). Retrying minimized...")
        posts = await _scrape_once("minimized")

    return posts

"""Scrape LinkedIn content search — per keyword: Posts + Past 24h, both Top match and Latest."""

import asyncio
import hashlib
import os
import urllib.parse
from typing import Any, Literal

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

SortMode = Literal["latest", "top_match"]

# LinkedIn content search sort param + UI labels
_SORT_CONFIG: dict[SortMode, dict[str, Any]] = {
    "latest": {
        "sortBy": "date_posted",
        "labels": ("Latest", "Date posted"),
    },
    "top_match": {
        "sortBy": "relevance",
        "labels": ("Top match", "Top Match", "Relevance"),
    },
}

# LinkedIn content search often hides /feed/update/ links — extract from result cards + text.
# Top match results frequently omit classic chameleon/result selectors; "Feed post" text fallback covers that.
EXTRACT_POSTS_JS = """() => {
    const items = [];
    const seen = new Set();

    function isNavBlob(text) {
        return text.includes('Skip to search')
            || text.includes('Get hired for')
            || text.includes('Try Premium for')
            || text.includes('Skip to main content')
            || text.startsWith('Home\\nMy Network');
    }

    function looksLikePost(text) {
        return text.includes('Feed post')
            || /\\b(hiring|hire|opening|vacancy|apply|walk-?in|job|recruit)\\b/i.test(text);
    }

    function pickAuthor(text, el) {
        if (el) {
            const fromEl = el.querySelector(
                '.update-components-actor__title, .entity-result__title-text, a[href*="/in/"] span[aria-hidden="true"], span[dir="ltr"]'
            );
            if (fromEl?.innerText?.trim()) return fromEl.innerText.trim().split('\\n')[0].trim();
        }
        const m = text.match(/^Feed post\\s*\\n?([^\\n•]+)/i)
            || text.match(/^([^\\n•]{2,80})\\s*•\\s*(1st|2nd|3rd|\\+|Verified|Following)/i);
        return m ? m[1].trim() : '';
    }

    function urnToFeed(blob) {
        const m = String(blob || '').match(/urn:li:(activity|ugcPost|share):(\\d+)/i);
        if (!m) return '';
        return `https://www.linkedin.com/feed/update/urn:li:${m[1]}:${m[2]}/`;
    }

    function permalinkFromHref(href) {
        const raw = (href || '').split('?')[0].split('#')[0];
        if (!raw) return '';
        if (/linkedin\\.com\\/company\\/[^/]+\\/posts\\/?$/i.test(raw)) return '';
        if (/\\/feed\\/update\\/urn:li:(?:activity|ugcPost|share):\\d+/i.test(raw)) return raw;
        const activitySlug = raw.match(/linkedin\\.com\\/posts\\/[^/?#]*activity-(\\d+)/i);
        if (activitySlug) return `https://www.linkedin.com/feed/update/urn:li:activity:${activitySlug[1]}/`;
        return urnToFeed(raw);
    }

    function pickUrl(el, text) {
        if (el) {
            for (const link of el.querySelectorAll('a[href]')) {
                const permalink = permalinkFromHref(link.href);
                if (permalink) return permalink;
            }
            let node = el;
            for (let i = 0; i < 8 && node; i++) {
                const blob = [
                    node.getAttribute?.('data-urn') || '',
                    node.getAttribute?.('data-chameleon-result-urn') || '',
                    node.getAttribute?.('data-id') || '',
                    node.id || '',
                ].join(' ');
                const fromAttr = urnToFeed(blob);
                if (fromAttr) return fromAttr;
                node = node.parentElement;
            }
            const fromHtml = urnToFeed(el.outerHTML || '');
            if (fromHtml) return fromHtml;
        }
        return urnToFeed(text);
    }

    function collectImages(el) {
        const imageUrls = [];
        if (!el) return imageUrls;
        const seenImg = new Set();
        for (const img of el.querySelectorAll('img')) {
            const src = (img.currentSrc || img.src || '').trim();
            if (!src || src.startsWith('data:')) continue;
            if (!/media\\.licdn\\.com|dms\\/image|licdn\\.com\\/dms/i.test(src)) continue;
            if (/ghost|emoji|presence|profile-displayphoto|company-logo|shrink_/i.test(src)) continue;
            const key = src.split('?')[0];
            if (seenImg.has(key)) continue;
            seenImg.add(key);
            imageUrls.push(src);
            if (imageUrls.length >= 5) break;
        }
        return imageUrls;
    }

    function pickCompanyUrl(el, text) {
        if (el) {
            for (const link of el.querySelectorAll('a[href*="/company/"]')) {
                const href = (link.href || '').split('?')[0];
                if (/linkedin\\.com\\/company\\//i.test(href)) {
                    return href.replace(/\\/$/, '');
                }
            }
        }
        const m = (text || '').match(/https?:\\/\\/(?:www\\.)?linkedin\\.com\\/company\\/[A-Za-z0-9\\-_%]+\\/?/i);
        return m ? m[0].replace(/\\/$/, '') : '';
    }

    function addItem(text, el) {
        const clean = (text || '').trim();
        if (clean.length < 80 || isNavBlob(clean) || !looksLikePost(clean)) return;
        const url = pickUrl(el, clean);
        const author = pickAuthor(clean, el);
        const company_url = pickCompanyUrl(el, clean);
        const key = url || `${author}|${clean.slice(0, 220)}`;
        if (seen.has(key)) return;
        seen.add(key);
        items.push({
            url,
            author,
            post_text: clean.slice(0, 8000),
            image_urls: collectImages(el),
            company_url,
        });
    }

    function addFromElement(el) {
        addItem(el.innerText || '', el);
    }

    const selectors = [
        '[data-chameleon-result-urn]',
        'li.reusable-search__result-container',
        '.feed-shared-update-v2',
        '.update-components-actor',
        'div[data-urn*="urn:li:activity"]',
        'div[data-urn*="urn:li:ugcPost"]',
        'div[data-view-name*="feed"]',
        'div[data-view-name*="search"]',
        'main ul > li',
        'main li',
        'main div[data-urn]',
        'div.scaffold-finite-scroll__content > div',
        'div.search-results-container li',
    ];

    for (const sel of selectors) {
        document.querySelectorAll(sel).forEach(el => {
            const text = (el.innerText || '').trim();
            if (text.length < 80 || text.length > 20000) return;
            if (looksLikePost(text) || sel.includes('chameleon') || sel.includes('reusable-search') || sel.includes('feed-shared')) {
                addFromElement(el);
            }
        });
    }

    for (const link of document.querySelectorAll(
        'a[href*="/feed/update/"], a[href*="/posts/"], a[href*="activity-"]'
    )) {
        let box = link.closest('[data-chameleon-result-urn], li, div[data-urn], article, div[role="article"], div[data-view-name]');
        if (!box) {
            let p = link.parentElement;
            for (let i = 0; i < 12 && p; i++) {
                if ((p.innerText || '').length > 100) { box = p; break; }
                p = p.parentElement;
            }
        }
        if (box) addFromElement(box);
    }

    // Fallback: LinkedIn Top match often keeps post text in the tree without classic card selectors.
    if (items.length === 0) {
        const root = document.querySelector('main') || document.body;
        const raw = root?.innerText || '';
        const chunks = raw.split(/(?=Feed post\\b)/i).filter(c => /Feed post/i.test(c));
        for (const chunk of chunks) {
            let body = chunk.trim();
            // Drop trailing chrome from next UI blocks
            body = body.split(/\\n(?:Promoted|About\\b|Accessibility|LinkedIn Corporation|Messaging)/)[0].trim();
            if (body.length < 80) continue;
            addItem(body, null);
        }
    }

    return items;
}"""


# Cap Share→Copy-link clicks so a scrape doesn't click every result card.
COPY_LINK_MAX = int(os.environ.get("COPY_LINK_MAX", "30"))


def build_search_url(keyword: str, sort_mode: SortMode = "latest") -> str:
    params = {
        "keywords": keyword,
        "origin": "FACETED_SEARCH",
        "sortBy": _SORT_CONFIG[sort_mode]["sortBy"],
        "datePosted": "past-24h",
    }
    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"https://www.linkedin.com/search/results/content/?{query}"


def _stable_url(item: dict[str, Any], keyword: str) -> str:
    from linkedin_agent.links import canonical_post_url

    permalink = canonical_post_url(item.get("url"))
    if permalink:
        return permalink
    digest = hashlib.sha256(
        f"{keyword}|{item.get('author', '')}|{item.get('post_text', '')[:500]}".encode("utf-8")
    ).hexdigest()[:16]
    slug = keyword.lower().replace(" ", "-")
    return f"https://linkedin.local/post/{slug}/{digest}"


async def _dismiss_linkedin_popovers(page: Page) -> None:
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(200)
        await page.keyboard.press("Escape")
    except Exception:
        pass


async def _read_copied_permalink(page: Page) -> str:
    from linkedin_agent.links import canonical_post_url

    raw = ""
    try:
        raw = await page.evaluate("() => navigator.clipboard.readText()")
    except Exception:
        raw = ""
    permalink = canonical_post_url(raw)
    if permalink:
        return permalink
    try:
        from_input = await page.evaluate(
            """() => {
                const inp = document.querySelector(
                    'input[value*="linkedin.com/feed/update"], input[value*="linkedin.com/posts/"]'
                );
                return inp && inp.value ? inp.value : '';
            }"""
        )
        return canonical_post_url(from_input)
    except Exception:
        return ""


async def _click_copy_link_on_card(page: Page, snippet: str) -> str:
    """Open Share (or ⋯) on a search card and click Copy link — same as the UI."""
    await _dismiss_linkedin_popovers(page)
    opened = await page.evaluate(
        """(snippet) => {
            const needle = String(snippet || '').slice(0, 70).toLowerCase();
            if (!needle) return { ok: false, reason: 'empty' };
            const cards = [...document.querySelectorAll(
                '[data-chameleon-result-urn], li.reusable-search__result-container, .feed-shared-update-v2, main ul > li'
            )];
            const card = cards.find(el => (el.innerText || '').toLowerCase().includes(needle));
            if (!card) return { ok: false, reason: 'no-card' };
            card.scrollIntoView({ block: 'center' });
            const buttons = [...card.querySelectorAll('button, [role="button"]')];
            const share = buttons.find(b => /share/i.test((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')));
            if (share) { share.click(); return { ok: true, step: 'share' }; }
            const more = buttons.find(b => /more|control menu|open overflow/i.test(b.getAttribute('aria-label') || ''));
            if (more) { more.click(); return { ok: true, step: 'more' }; }
            return { ok: false, reason: 'no-share' };
        }""",
        snippet,
    )
    if not opened or not opened.get("ok"):
        return ""
    await page.wait_for_timeout(500)
    clicked = await page.evaluate(
        """() => {
            const nodes = [...document.querySelectorAll('button, [role="menuitem"], [role="button"], li, div, span')];
            const el = nodes.find(n => {
                const t = (n.innerText || '').replace(/\\s+/g, ' ').trim();
                const al = n.getAttribute('aria-label') || '';
                return /copy link( to post)?/i.test(t) || /copy link( to post)?/i.test(al);
            });
            if (!el) return false;
            el.click();
            return true;
        }"""
    )
    await page.wait_for_timeout(400)
    permalink = await _read_copied_permalink(page) if clicked else ""
    await _dismiss_linkedin_popovers(page)
    return permalink


async def _resolve_permalinks_via_copy_link(page: Page, posts: list[dict[str, Any]]) -> None:
    """Fill missing /feed/update/ URLs using LinkedIn's Share → Copy link control."""
    from linkedin_agent.links import canonical_post_url

    missing = [p for p in posts if not canonical_post_url(p.get("url"))]
    if not missing:
        return
    to_fix = missing[:COPY_LINK_MAX]
    print(f"  Copy-link for {len(to_fix)} post(s) missing permalinks...")
    filled = 0
    for post in to_fix:
        snippet = (post.get("author") or "") + "\n" + (post.get("post_text") or "")
        snippet = snippet.replace("Feed post", "").strip()
        if len(snippet) < 20:
            continue
        try:
            permalink = await _click_copy_link_on_card(page, snippet[:90])
        except Exception:
            permalink = ""
        if permalink:
            post["url"] = permalink
            filled += 1
        await page.wait_for_timeout(250)
    print(f"  Copy-link filled {filled}/{len(to_fix)} permalinks")


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


async def _dismiss_open_filter_panels(page: Page) -> None:
    """Close date/sort dropdowns that block scrolling/extraction (e.g. Past 24 hours open)."""
    try:
        show = page.locator('button:has-text("Show results")').first
        if await show.count() > 0 and await show.is_visible():
            await show.click()
            await page.wait_for_timeout(1500)
            return
    except Exception:
        pass
    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(400)
    except Exception:
        pass


async def _apply_search_filters(page: Page, sort_mode: SortMode = "latest") -> None:
    for label in ("Posts", "Post"):
        if await click_filter_button(page, label):
            break
    await _dismiss_open_filter_panels(page)

    for label in _SORT_CONFIG[sort_mode]["labels"]:
        if await click_filter_button(page, label):
            break
    await _dismiss_open_filter_panels(page)

    # URL already has datePosted=past-24h; only reinforce if the chip is missing.
    try:
        chip = page.locator('button:has-text("Past 24 hours"), button:has-text("Past 24 Hours")').first
        already = await chip.count() > 0 and await chip.is_visible()
    except Exception:
        already = False
    if not already:
        for label in ("Past 24 hours", "Past 24 Hours", "Past 24h", "24 hours"):
            if await click_filter_button(page, label):
                # Dropdown opened — select radio + Show results
                try:
                    radio = page.locator('text=Past 24 hours').first
                    if await radio.count() > 0:
                        await radio.click()
                        await page.wait_for_timeout(400)
                except Exception:
                    pass
                break
    await _dismiss_open_filter_panels(page)


async def _debug_page_state(page: Page, keyword: str) -> None:
    stats = await page.evaluate(
        """() => {
            const mainText = document.querySelector('main')?.innerText || document.body?.innerText || '';
            const feedChunks = mainText.split(/(?=Feed post\\b)/i).filter(c => /Feed post/i.test(c)).length;
            return {
                links: document.querySelectorAll('a[href*="/feed/update/"], a[href*="/posts/"]').length,
                chameleon: document.querySelectorAll('[data-chameleon-result-urn]').length,
                results: document.querySelectorAll('li.reusable-search__result-container').length,
                feedPosts: mainText.includes('Feed post'),
                feedChunks,
                title: document.title,
                snippet: mainText.slice(0, 320).replace(/\\s+/g, ' '),
            };
        }"""
    )
    print(
        f"  Debug [{keyword}]: chameleon={stats.get('chameleon')} "
        f"results={stats.get('results')} feed_post_text={stats.get('feedPosts')} "
        f"feed_chunks={stats.get('feedChunks')} post_links={stats.get('links')}"
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
                "image_urls": list(item.get("image_urls") or []),
                "company_url": (item.get("company_url") or "").strip(),
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


async def _search_keyword_with_sort(
    page: Page,
    *,
    keyword: str,
    role_tag: str,
    sort_mode: SortMode,
    posts: list[dict[str, Any]],
    seen_urls: set[str],
) -> None:
    """Run one keyword search for a single sort mode and merge into posts."""
    label = "Latest" if sort_mode == "latest" else "Top match"
    url = build_search_url(keyword, sort_mode)
    print(f"\n  Searching: {keyword} [{label}]")
    await safe_goto(page, url)
    await _apply_search_filters(page, sort_mode)
    await _wait_for_results(page)

    before = len(posts)
    _merge_batch(await page.evaluate(EXTRACT_POSTS_JS) or [], keyword, role_tag, posts, seen_urls)

    # Double budget vs prior default: each sort gets half of SCROLL_COUNT (min 6).
    scroll_passes = max(6, SCROLL_COUNT // 2)
    print(f"  Scrolling {scroll_passes}x ({label})...")
    for i in range(scroll_passes):
        if len(posts) >= MAX_POSTS_PER_SEARCH:
            break
        await page.evaluate(
            """() => {
                const main = document.querySelector('main') || document.body;
                main.scrollTop = main.scrollHeight;
                window.scrollTo(0, document.body.scrollHeight);
                const scroller = document.querySelector('.scaffold-finite-scroll__content')?.parentElement;
                if (scroller) scroller.scrollTop = scroller.scrollHeight;
            }"""
        )
        await page.wait_for_timeout(2200)
        _merge_batch(await page.evaluate(EXTRACT_POSTS_JS) or [], keyword, role_tag, posts, seen_urls)
        print(f"    scroll {i + 1}/{scroll_passes} — {len(posts)} unique posts so far")

    added = len(posts) - before
    print(f"  [{label}] +{added} new posts (total {len(posts)})")
    if added == 0:
        await _debug_page_state(page, f"{keyword}_{sort_mode}")
    else:
        await _resolve_permalinks_via_copy_link(page, posts[before:])


async def search_role(page: Page, role: dict[str, str]) -> list[dict[str, Any]]:
    """For each keyword: scrape Top match AND Latest (Past 24h), deduped."""
    keyword = role["keyword"]
    role_tag = role["role_tag"]
    posts: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    # Top match first (relevance), then Latest — covers both ranking surfaces.
    for sort_mode in ("top_match", "latest"):
        if len(posts) >= MAX_POSTS_PER_SEARCH:
            break
        try:
            await _search_keyword_with_sort(
                page,
                keyword=keyword,
                role_tag=role_tag,
                sort_mode=sort_mode,  # type: ignore[arg-type]
                posts=posts,
                seen_urls=seen_urls,
            )
        except Exception as exc:
            print(f"  ✗ Search failed for {keyword} [{sort_mode}]: {exc}")

        if sort_mode == "top_match":
            await asyncio.sleep(3)

    posts = posts[:MAX_POSTS_PER_SEARCH]
    if not posts:
        print(f"  Found 0 posts for {keyword} (both sorts)")
    else:
        print(f"  Found {len(posts)} posts for {keyword} (Top match + Latest, deduped)")
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

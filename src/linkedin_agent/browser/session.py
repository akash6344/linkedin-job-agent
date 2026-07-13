"""Persistent Chrome session for LinkedIn."""

import asyncio
import os
import subprocess
import sys
from typing import Any, Literal

from playwright.async_api import BrowserContext, Page, async_playwright

from linkedin_agent.config import (
    BROWSER_DATA_DIR,
    BROWSER_MODE,
    HIDE_CHROME,
    PAGE_LOAD_DELAY_SEC,
    USE_CHROME_CHANNEL,
)

BrowserMode = Literal["minimized", "headless", "visible"]

# Background task that keeps the automation window off-screen during a scrape.
_hide_task: asyncio.Task | None = None


def resolve_browser_mode(mode: str | None = None) -> tuple[bool, list[str], str]:
    """
    LinkedIn often returns 0 results in headless mode.
    Default `minimized` uses real Chrome off-screen — works like background.
    """
    mode = (mode or BROWSER_MODE).lower()
    if mode == "headless":
        return True, [], "headless"
    if mode == "visible":
        return False, [], "visible"
    # minimized — headed Chrome, parked far off-screen (LinkedIn blocks true headless)
    return False, [
        "--start-minimized",
        "--window-position=-32000,-32000",
        "--window-size=1280,900",
        "--disable-infobars",
        "--disable-notifications",
        "--noerrdialogs",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
    ], "minimized (hidden Chrome)"


def _hide_chrome_mac() -> None:
    """Park LinkedIn automation windows off-screen / minimized without killing user Chrome."""
    if sys.platform != "darwin":
        return

    script = r'''
    set targets to {"Chromium", "Google Chrome"}
    repeat with appName in targets
      try
        tell application "System Events"
          if exists process appName then
            tell process appName
              repeat with w in windows
                try
                  set wTitle to name of w as text
                  if wTitle contains "LinkedIn" or wTitle contains "linkedin" or wTitle is "" or wTitle contains "about:blank" then
                    set position of w to {-32000, -32000}
                    set size of w to {1280, 900}
                    try
                      set value of attribute "AXMinimized" of w to true
                    end try
                  end if
                end try
              end repeat
            end tell
          end if
        end tell
      end try
    end repeat
    try
      tell application "Google Chrome"
        repeat with w in windows
          try
            set t to title of w as text
            if t contains "LinkedIn" or t contains "linkedin" or t is "" then
              set miniaturized of w to true
              set bounds of w to {-32000, -32000, -30720, -31100}
            end if
          end try
        end repeat
      end tell
    end try
    '''
    try:
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            timeout=8,
            check=False,
        )
    except Exception:
        pass


async def _suppress_chrome_window() -> None:
    await asyncio.to_thread(_hide_chrome_mac)


async def _park_window_via_cdp(context: BrowserContext) -> None:
    """Force the Playwright window off-screen via CDP (most reliable hide)."""
    for page in list(context.pages):
        if page.is_closed():
            continue
        try:
            session = await context.new_cdp_session(page)
            try:
                result = await session.send("Browser.getWindowForTarget")
                window_id = result.get("windowId")
                if window_id is None:
                    continue
                await session.send(
                    "Browser.setWindowBounds",
                    {
                        "windowId": window_id,
                        "bounds": {
                            "left": -32000,
                            "top": -32000,
                            "width": 1280,
                            "height": 900,
                            "windowState": "minimized",
                        },
                    },
                )
            finally:
                try:
                    await session.detach()
                except Exception:
                    pass
        except Exception:
            continue


async def _hide_loop(context: BrowserContext) -> None:
    """Keep re-parking the window — Chrome often reappears after navigation."""
    while True:
        try:
            await _park_window_via_cdp(context)
            await _suppress_chrome_window()
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(1.5)


def start_chrome_hide_loop(context: BrowserContext) -> None:
    global _hide_task
    if not HIDE_CHROME or BROWSER_MODE != "minimized":
        return
    if _hide_task and not _hide_task.done():
        return
    _hide_task = asyncio.create_task(_hide_loop(context))


async def stop_chrome_hide_loop() -> None:
    global _hide_task
    if _hide_task and not _hide_task.done():
        _hide_task.cancel()
        try:
            await _hide_task
        except asyncio.CancelledError:
            pass
    _hide_task = None


async def create_browser_context(
    headless: bool | None = None,
    mode: str | None = None,
    *,
    hide_chrome: bool | None = None,
) -> tuple[Any, BrowserContext]:
    if headless is not None:
        resolved_headless = headless
        extra_args: list[str] = []
        label = "headless" if headless else "visible"
        resolved_mode = "visible" if not headless else "headless"
    else:
        resolved_mode = (mode or BROWSER_MODE).lower()
        resolved_headless, extra_args, label = resolve_browser_mode(mode)

    if hide_chrome is None:
        hide_chrome = HIDE_CHROME and not resolved_headless and resolved_mode == "minimized"

    playwright = await async_playwright().start()
    BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    launch_kwargs: dict[str, Any] = {
        "user_data_dir": str(BROWSER_DATA_DIR),
        "headless": resolved_headless,
        "viewport": {"width": 1280, "height": 900},
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--no-first-run",
            "--no-default-browser-check",
            *extra_args,
        ],
        "ignore_default_args": ["--enable-automation"],
    }
    if USE_CHROME_CHANNEL:
        launch_kwargs["channel"] = "chrome"

    # Reduce focus-stealing on macOS when possible
    env = os.environ.copy()
    if hide_chrome and sys.platform == "darwin":
        env.setdefault("PLAYWRIGHT_CHROMIUM_USE_HEADLESS_NEW", "0")
    launch_kwargs["env"] = env

    context = await playwright.chromium.launch_persistent_context(**launch_kwargs)
    await context.add_init_script(
        """
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = window.chrome || { runtime: {} };
        """
    )
    context._linkedin_mode_label = label  # type: ignore[attr-defined]

    if hide_chrome:
        await _park_window_via_cdp(context)
        await _suppress_chrome_window()
        await asyncio.sleep(0.3)
        await _park_window_via_cdp(context)
        await _suppress_chrome_window()
        start_chrome_hide_loop(context)

    return playwright, context


async def get_live_page(context: BrowserContext, page: Page | None) -> Page:
    if page is not None and not page.is_closed():
        return page
    if context.pages:
        candidate = context.pages[0]
        if not candidate.is_closed():
            return candidate
    return await context.new_page()


async def safe_goto(page: Page, url: str, retries: int = 3) -> None:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            if page.is_closed():
                raise RuntimeError("Browser tab was closed")
            try:
                await page.goto(url, wait_until="networkidle", timeout=90000)
            except Exception:
                await page.goto(url, wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(PAGE_LOAD_DELAY_SEC * 1000)
            if HIDE_CHROME and BROWSER_MODE == "minimized":
                try:
                    await _park_window_via_cdp(page.context)
                except Exception:
                    pass
                await _suppress_chrome_window()
            return
        except Exception as exc:
            last_error = exc
            print(f"  Navigation retry {attempt}/{retries}: {exc}")
            await asyncio.sleep(2 * attempt)
    raise RuntimeError(f"Failed to open {url}") from last_error


async def ensure_logged_in(page: Page, *, interactive: bool = False) -> None:
    await safe_goto(page, "https://www.linkedin.com/feed/")

    logged_in = await page.evaluate(
        """() => {
            const href = window.location.href || '';
            if (href.includes('/login') || href.includes('/uas/login')) return false;
            const signIn = document.querySelector('a[href*="/login"], button[data-tracking-control-name*="login"]');
            const nav = document.querySelector('.global-nav, nav, header');
            const main = document.querySelector('main, .scaffold-finite-scroll');
            return !!main && !!nav && !signIn;
        }"""
    )

    if logged_in:
        print("  ✓ LinkedIn session active")
        return

    if interactive or sys.stdin.isatty():
        print("\n" + "=" * 60)
        print("Please log in to LinkedIn in the Chrome window.")
        print("Press Enter when you see your feed.")
        print("=" * 60 + "\n")
        input()
        await page.wait_for_timeout(2000)
        return

    print("\n  ⚠ LinkedIn login not detected (scheduled/wake run — not blocking).")
    print("  Run `python -m linkedin_agent login` if scraping returns empty results.")


async def click_filter_button(page: Page, label: str) -> bool:
    selectors = [
        f'button:has-text("{label}")',
        f'label:has-text("{label}")',
        f'[role="button"]:has-text("{label}")',
        f'span:text-is("{label}")',
        f'div[role="radio"]:has-text("{label}")',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if await loc.count() > 0 and await loc.is_visible():
                await loc.click()
                await page.wait_for_timeout(1500)
                return True
        except Exception:
            continue
    return False

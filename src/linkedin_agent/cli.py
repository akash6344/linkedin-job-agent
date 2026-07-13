"""CLI entry point."""

import argparse
import asyncio
import sys
import traceback
from datetime import datetime, timezone

from linkedin_agent.browser.session import create_browser_context, ensure_logged_in
from linkedin_agent.notify.service import RunSummary, send_run_summary
from linkedin_agent.pipeline import run_pipeline
from linkedin_agent.run_log import setup_run_logging


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin-agent",
        description="LinkedIn post job agent — scrape, classify, email apply, Telegram notify.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("run", help="Full pipeline (default)")
    sub.add_parser("login", help="Open LinkedIn and save login session")
    sub.add_parser("test-email", help="Verify Gmail App Password works")
    return parser


def _run_with_logging(coro_factory) -> int:
    log_file = setup_run_logging()
    print(f"Python: {sys.executable}")
    print(f"Log: {log_file}\n")

    summary = RunSummary(status="error", started_at=datetime.now(timezone.utc).isoformat())
    try:
        summary = asyncio.run(coro_factory())
        return 0
    except KeyboardInterrupt:
        summary.error = "Interrupted by user"
        return 1
    except Exception:
        summary.error = traceback.format_exc()
        print(f"\nFatal error:\n{summary.error}")
        return 1
    finally:
        send_run_summary(summary)


async def _cmd_run() -> RunSummary:
    return await run_pipeline()


async def _cmd_login() -> RunSummary:
    started_at = datetime.now(timezone.utc).isoformat()
    playwright, context = await create_browser_context(headless=False, mode="visible", hide_chrome=False)
    try:
        from linkedin_agent.browser.session import get_live_page

        page = await get_live_page(context, None)
        await ensure_logged_in(page, interactive=True)
        print("\nLinkedIn session saved in .linkedin_browser/")
        print("Background runs use LINKEDIN_HEADLESS=1 (no window).")
        input("Press Enter to exit...")
    finally:
        await context.close()
        await playwright.stop()
    return RunSummary(status="success", started_at=started_at)


async def _cmd_test_email() -> RunSummary:
    from linkedin_agent.apply.test_email import test_gmail_connection

    started_at = datetime.now(timezone.utc).isoformat()
    test_gmail_connection()
    return RunSummary(status="success", started_at=started_at)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    command = args.command or "run"

    if command == "run":
        code = _run_with_logging(_cmd_run)
    elif command == "login":
        code = _run_with_logging(_cmd_login)
    elif command == "test-email":
        try:
            asyncio.run(_cmd_test_email())
            code = 0
        except Exception as exc:
            print(f"\n✗ {exc}")
            code = 1
    else:
        parser.print_help()
        code = 1

    sys.exit(code)


if __name__ == "__main__":
    main()

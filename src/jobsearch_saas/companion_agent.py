"""
Local companion runner: scrape LinkedIn on this machine, upload to LetItApply.

Used by the Electron app (and can be run from CLI):

  python -m jobsearch_saas.companion_agent login --email you@x.com --password ...
  python -m jobsearch_saas.companion_agent connect-linkedin
  python -m jobsearch_saas.companion_agent search
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from jobsearch_saas.config import BASE_URL, PROJECT_ROOT

STATE_DIR = Path(os.environ.get("LETITAPPLY_COMPANION_DIR", str(Path.home() / ".letitapply-companion")))
STATE_FILE = STATE_DIR / "state.json"


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def _save_state(data: dict[str, Any]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _api(method: str, path: str, *, token: str = "", body: dict | None = None) -> dict[str, Any]:
    api_base = os.environ.get("LETITAPPLY_API", BASE_URL).rstrip("/")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{api_base}{path}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        try:
            parsed = json.loads(detail)
            detail = parsed.get("detail") or detail
        except Exception:
            pass
        raise RuntimeError(f"API {exc.code}: {detail}") from exc


def cmd_login(args: argparse.Namespace) -> int:
    result = _api(
        "POST",
        "/api/companion/login",
        body={
            "email": args.email,
            "password": args.password,
            "device_id": args.device_id or _load_state().get("device_id", ""),
            "device_name": args.device_name or "LetItApply Companion",
        },
    )
    state = _load_state()
    state.update(
        {
            "token": result["token"],
            "device_id": result["device_id"],
            "email": result["user"]["email"],
            "api_base": os.environ.get("LETITAPPLY_API", BASE_URL).rstrip("/"),
        }
    )
    _save_state(state)
    print(json.dumps({"ok": True, "email": result["user"]["email"], "plan": result["plan"]["plan_id"]}))
    return 0


def cmd_me(_: argparse.Namespace) -> int:
    state = _load_state()
    if not state.get("token"):
        print(json.dumps({"ok": False, "error": "Not signed in"}))
        return 1
    me = _api("GET", "/api/companion/me", token=state["token"])
    print(json.dumps({"ok": True, **me}))
    return 0


async def _linkedin_login() -> None:
    from linkedin_agent.browser.session import create_browser_context, ensure_logged_in, get_live_page

    playwright, context = await create_browser_context(headless=False, mode="visible", hide_chrome=False)
    try:
        page = await get_live_page(context, None)
        await ensure_logged_in(page, interactive=True)
        print(json.dumps({"ok": True, "linkedin_connected": True}))
    finally:
        await context.close()
        await playwright.stop()


def cmd_connect_linkedin(_: argparse.Namespace) -> int:
    state = _load_state()
    token = state.get("token")
    if not token:
        print(json.dumps({"ok": False, "error": "Sign in to LetItApply first"}))
        return 1
    asyncio.run(_linkedin_login())
    _api(
        "POST",
        "/api/companion/status",
        token=token,
        body={"linkedin_connected": True, "last_error": ""},
    )
    state["linkedin_connected"] = True
    _save_state(state)
    return 0


async def _run_search(roles: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Search LinkedIn using roles from the signed-in SaaS account only (no personal CLI fallbacks)."""
    from linkedin_agent.browser.session import create_browser_context, ensure_logged_in, get_live_page
    from linkedin_agent.scrape.service import search_role

    if not roles:
        raise ValueError("No roles configured in LetItApply. Add roles in onboarding/settings first.")

    playwright, context = await create_browser_context(mode="minimized")
    page = None
    all_posts: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        page = await get_live_page(context, None)
        await ensure_logged_in(page, interactive=False)
        for role in roles:
            page = await get_live_page(context, page)
            try:
                posts = await search_role(page, role)
            except Exception as exc:
                print(f"search failed for {role.get('keyword')}: {exc}", file=sys.stderr)
                posts = []
            for post in posts:
                if post["url"] in seen:
                    continue
                seen.add(post["url"])
                all_posts.append(post)
    finally:
        from linkedin_agent.browser.session import stop_chrome_hide_loop

        await stop_chrome_hide_loop()
        await context.close()
        await playwright.stop()
    return all_posts


def cmd_search(args: argparse.Namespace) -> int:
    state = _load_state()
    token = state.get("token")
    if not token:
        print(json.dumps({"ok": False, "error": "Sign in to LetItApply first"}))
        return 1

    try:
        me = _api("GET", "/api/companion/me", token=token)
        role_names = (me.get("prefs") or {}).get("roles") or []
        if not role_names:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": "No roles in your LetItApply profile. Add roles in onboarding/settings, then retry.",
                    }
                )
            )
            return 1
        roles = [
            {
                "keyword": f"{name} hiring",
                "role_tag": name.lower().replace(" ", "_")[:40],
                "resume_key": "account",
                "email_template": "account",
            }
            for name in role_names[:4]
        ]
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"Could not load account prefs: {exc}"}))
        return 1

    try:
        posts = asyncio.run(_run_search(roles))
    except Exception as exc:
        _api(
            "POST",
            "/api/companion/status",
            token=token,
            body={"linkedin_connected": False, "last_error": str(exc)[:300]},
        )
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    if not posts:
        print(json.dumps({"ok": True, "accepted": 0, "message": "No posts found"}))
        return 0

    try:
        result = _api("POST", "/api/companion/posts", token=token, body={"posts": posts})
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1

    print(json.dumps({"ok": True, "scraped": len(posts), **result}))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="letitapply-companion")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login")
    login.add_argument("--email", required=True)
    login.add_argument("--password", required=True)
    login.add_argument("--device-id", default="")
    login.add_argument("--device-name", default="LetItApply Companion")

    sub.add_parser("me")
    sub.add_parser("connect-linkedin")
    sub.add_parser("search")

    args = parser.parse_args()
    # Ensure linkedin_agent package is importable from same repo
    src = str(PROJECT_ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)

    if args.command == "login":
        raise SystemExit(cmd_login(args))
    if args.command == "me":
        raise SystemExit(cmd_me(args))
    if args.command == "connect-linkedin":
        raise SystemExit(cmd_connect_linkedin(args))
    if args.command == "search":
        raise SystemExit(cmd_search(args))
    parser.print_help()
    raise SystemExit(1)


if __name__ == "__main__":
    main()

"""Google OAuth login for admin panel."""

from __future__ import annotations

import urllib.parse
from typing import Any

from fastapi import Request

from jobsearch_saas.config import (
    ADMIN_ALLOWED_EMAILS,
    GOOGLE_ADMIN_REDIRECT_URI,
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
)
from jobsearch_saas.email.oauth import exchange_code, fetch_userinfo, oauth_configured

ADMIN_SESSION_KEY = "admin_email"


def admin_oauth_configured() -> bool:
    return oauth_configured()


def build_admin_auth_url(*, state: str) -> str:
    if not oauth_configured():
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not configured")
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_ADMIN_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def admin_from_session(request: Request) -> str | None:
    email = request.session.get(ADMIN_SESSION_KEY)
    if not email:
        return None
    email_norm = str(email).strip().lower()
    if email_norm not in ADMIN_ALLOWED_EMAILS:
        return None
    return email_norm


def login_admin(request: Request, *, code: str) -> str:
    tokens = exchange_code_for_admin(code)
    access = tokens["access_token"]
    info = fetch_userinfo(access)
    email = (info.get("email") or "").strip().lower()
    if not email or email not in ADMIN_ALLOWED_EMAILS:
        raise PermissionError("Access denied — your Google account is not authorized for admin.")
    request.session[ADMIN_SESSION_KEY] = email
    return email


def logout_admin(request: Request) -> None:
    request.session.pop(ADMIN_SESSION_KEY, None)


def exchange_code_for_admin(code: str) -> dict[str, Any]:
    """Exchange OAuth code using admin redirect URI."""
    import json
    import urllib.request

    data = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_ADMIN_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

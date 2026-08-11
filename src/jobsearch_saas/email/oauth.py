"""Gmail OAuth connection — never store Gmail app passwords for SaaS users."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

from jobsearch_saas import db
from jobsearch_saas.config import (
    GOOGLE_CLIENT_ID,
    GOOGLE_CLIENT_SECRET,
    GOOGLE_REDIRECT_URI,
    GMAIL_READONLY_SCOPE,
    GMAIL_SEND_SCOPE,
    TOKEN_FERNET_KEY,
)

try:
    from cryptography.fernet import Fernet, InvalidToken
except ImportError:  # pragma: no cover - dependency installed via pyproject
    Fernet = None  # type: ignore
    InvalidToken = Exception  # type: ignore


def oauth_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)


def _fernet() -> Any:
    if Fernet is None:
        raise RuntimeError("cryptography package required for token encryption")
    if TOKEN_FERNET_KEY:
        raw = TOKEN_FERNET_KEY.encode("utf-8") if isinstance(TOKEN_FERNET_KEY, str) else TOKEN_FERNET_KEY
        return Fernet(raw)
    # Deterministic dev key from secret — set SAAS_TOKEN_FERNET_KEY in production
    from jobsearch_saas.config import SECRET_KEY
    import hashlib

    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest()))


def encrypt_token(token: str) -> str:
    if not token:
        return ""
    return _fernet().encrypt(token.encode("utf-8")).decode("utf-8")


def decrypt_token(token_enc: str) -> str:
    if not token_enc:
        return ""
    try:
        return _fernet().decrypt(token_enc.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise RuntimeError("Could not decrypt OAuth token") from exc


def build_auth_url(*, state: str, include_send: bool = True, include_read: bool = False) -> str:
    if not oauth_configured():
        raise RuntimeError("GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET not configured")
    scopes = ["openid", "email", "profile"]
    if include_send:
        scopes.append(GMAIL_SEND_SCOPE)
    if include_read:
        scopes.append(GMAIL_READONLY_SCOPE)
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)


def exchange_code(code: str) -> dict[str, Any]:
    data = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
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


def fetch_userinfo(access_token: str) -> dict[str, Any]:
    req = urllib.request.Request(
        "https://www.googleapis.com/oauth2/v2/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode())


def save_connection(
    user_id: str,
    *,
    email_address: str,
    access_token: str,
    refresh_token: str,
    scopes: list[str],
) -> None:
    send_enabled = GMAIL_SEND_SCOPE in scopes or any("gmail.send" in s for s in scopes)
    read_enabled = GMAIL_READONLY_SCOPE in scopes or any("gmail.readonly" in s for s in scopes)
    with db.connect() as conn:
        conn.execute(
            """
            INSERT INTO email_connections (
                user_id, provider, email_address, access_token_enc, refresh_token_enc,
                scopes_json, send_enabled, read_enabled, updated_at
            ) VALUES (?, 'gmail', ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                email_address=excluded.email_address,
                access_token_enc=excluded.access_token_enc,
                refresh_token_enc=excluded.refresh_token_enc,
                scopes_json=excluded.scopes_json,
                send_enabled=excluded.send_enabled,
                read_enabled=excluded.read_enabled,
                updated_at=excluded.updated_at
            """,
            (
                user_id,
                email_address,
                encrypt_token(access_token),
                encrypt_token(refresh_token),
                db.dumps(scopes),
                1 if send_enabled else 0,
                1 if read_enabled else 0,
                db.utc_now(),
            ),
        )
        db.audit(
            conn,
            user_id=user_id,
            action="email.oauth_connected",
            entity_type="email_connection",
            entity_id=user_id,
            detail={"email": email_address, "send": send_enabled, "read": read_enabled},
        )


def get_connection(user_id: str) -> dict[str, Any] | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM email_connections WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return db.row_to_dict(row)


def disconnect(user_id: str) -> None:
    with db.connect() as conn:
        conn.execute("DELETE FROM email_connections WHERE user_id = ?", (user_id,))
        db.audit(conn, user_id=user_id, action="email.oauth_disconnected", entity_type="email_connection")


def refresh_access_token(user_id: str) -> str:
    conn_row = get_connection(user_id)
    if not conn_row:
        raise RuntimeError("No email connection")
    refresh = decrypt_token(conn_row["refresh_token_enc"])
    if not refresh:
        raise RuntimeError("Missing refresh token — reconnect Gmail")
    data = urllib.parse.urlencode(
        {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode())
    access = payload["access_token"]
    with db.connect() as conn:
        conn.execute(
            "UPDATE email_connections SET access_token_enc = ?, updated_at = ? WHERE user_id = ?",
            (encrypt_token(access), db.utc_now(), user_id),
        )
    return access


def send_mail_via_oauth(
    user_id: str,
    *,
    to_email: str,
    subject: str,
    body: str,
    attachment_path: Path | None = None,
) -> None:
    """Send email using the user's Gmail OAuth token (human-approved send path)."""
    connection = get_connection(user_id)
    if not connection or not connection.get("send_enabled"):
        raise RuntimeError("Gmail send not connected. Connect Google OAuth with send permission.")
    access = decrypt_token(connection["access_token_enc"])
    msg = MIMEMultipart()
    msg["To"] = to_email
    msg["From"] = connection["email_address"]
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))
    if attachment_path and attachment_path.exists():
        with attachment_path.open("rb") as f:
            part = MIMEApplication(f.read(), Name=attachment_path.name)
            part["Content-Disposition"] = f'attachment; filename="{attachment_path.name}"'
            msg.attach(part)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    payload = json.dumps({"raw": raw}).encode()

    def _send(token: str) -> None:
        req = urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            data=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp.read()

    try:
        _send(access)
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            access = refresh_access_token(user_id)
            _send(access)
        else:
            raise RuntimeError(f"Gmail send failed: {exc}") from exc

    with db.connect() as conn:
        db.audit(
            conn,
            user_id=user_id,
            action="email.sent",
            entity_type="email",
            detail={"to": to_email, "subject": subject},
        )

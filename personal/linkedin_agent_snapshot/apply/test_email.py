"""Verify Gmail SMTP credentials."""

import smtplib

from linkedin_agent.config import GMAIL_ADDRESS, GMAIL_APP_PASSWORD


def test_gmail_connection() -> None:
    if not GMAIL_APP_PASSWORD:
        raise RuntimeError("Set GMAIL_APP_PASSWORD in .env first.")

    password = GMAIL_APP_PASSWORD.replace(" ", "")
    print(f"Testing Gmail SMTP for {GMAIL_ADDRESS} ...")

    if len(password) != 16:
        print("⚠ Password is not 16 characters — this is probably your normal Gmail password.")
        print("  Google requires an App Password: https://myaccount.google.com/apppasswords")
        print("  (Needs 2-Step Verification enabled on your Google account.)")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
        server.login(GMAIL_ADDRESS, password)

    print("✓ Gmail login successful — ready to send applications.")

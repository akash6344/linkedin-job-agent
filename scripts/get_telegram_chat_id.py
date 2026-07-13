#!/usr/bin/env python3
"""Find your Telegram chat ID after messaging @whobatbot."""

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from linkedin_agent.config import TELEGRAM_BOT_TOKEN


def main() -> None:
    token = TELEGRAM_BOT_TOKEN or input("Paste TELEGRAM_BOT_TOKEN: ").strip()
    if not token:
        print("No token provided.")
        sys.exit(1)

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print(f"Error: {exc.read().decode()}")
        sys.exit(1)

    if not data.get("ok"):
        print(f"API error: {data}")
        sys.exit(1)

    updates = data.get("result", [])
    if not updates:
        print("No messages yet.")
        print("1. Open https://t.me/whobatbot in Telegram")
        print("2. Send /start")
        print("3. Run this script again")
        sys.exit(1)

    seen: set[int] = set()
    print("\nYour chat ID(s):\n")
    for update in updates:
        msg = update.get("message") or update.get("edited_message") or {}
        chat = msg.get("chat", {})
        chat_id = chat.get("id")
        if not chat_id or chat_id in seen:
            continue
        seen.add(chat_id)
        name = f"{chat.get('first_name', '')} {chat.get('last_name', '')}".strip()
        username = chat.get("username", "")
        print(f"  TELEGRAM_CHAT_ID={chat_id}  ({name} @{username})")

    print("\nAdd TELEGRAM_CHAT_ID to your .env file.")


if __name__ == "__main__":
    main()

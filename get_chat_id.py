"""
Find your Telegram chat ID.

Steps:
  1. In Telegram, open your bot and send it any message (e.g. "hi").
  2. Run:  python get_chat_id.py
It prints the chat ID of whoever recently messaged the bot.
Copy the number into TELEGRAM_CHAT_ID in your .env file.
"""

import os
import sys

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
if not token:
    token = input("Paste your bot token: ").strip()

url = f"https://api.telegram.org/bot{token}/getUpdates"
try:
    data = requests.get(url, timeout=10).json()
except Exception as exc:  # noqa: BLE001 - small helper script
    sys.exit(f"Request failed: {exc}")

if not data.get("ok"):
    sys.exit(f"Telegram error: {data}")

updates = data.get("result", [])
if not updates:
    print("No messages found. Send your bot a message in Telegram, then run this again.")
    sys.exit(0)

seen = {}
for upd in updates:
    msg = upd.get("message") or upd.get("edited_message") or {}
    chat = msg.get("chat") or {}
    if chat.get("id") is not None:
        name = chat.get("username") or chat.get("first_name") or chat.get("title") or ""
        seen[chat["id"]] = name

print("Found these chat IDs:")
for cid, name in seen.items():
    print(f"  {cid}   {name}")
print("\nCopy the number into TELEGRAM_CHAT_ID in your .env file.")

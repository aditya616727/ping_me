"""
ping_me - a tiny GET API that pings your phone over Telegram.

Hit  GET /ping  and you get a Telegram message.

Optional query params on /ping:
  ?msg=Custom text   -> send your own text instead of the default
  ?key=SECRET        -> required only when PING_SECRET is set (keeps strangers out)
"""

import os
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import FastAPI, HTTPException, Query, Request

# Load variables from a local .env file, if python-dotenv is installed.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
PING_SECRET = os.getenv("PING_SECRET", "").strip()  # optional

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

app = FastAPI(
    title="ping_me",
    description="Hit the endpoint, get a Telegram ping on your phone.",
    version="1.0.0",
)


def send_telegram(text: str) -> None:
    """Send `text` to your Telegram chat. Raises HTTPException on failure."""
    if not BOT_TOKEN or not CHAT_ID:
        raise HTTPException(
            status_code=500,
            detail="Server not configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.",
        )
    try:
        resp = requests.post(
            TELEGRAM_URL,
            json={"chat_id": CHAT_ID, "text": text, "disable_web_page_preview": True},
            timeout=10,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach Telegram: {exc}")
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Telegram API error: {resp.text}")


@app.get("/")
def health():
    """Health check - confirms the service is up and configured."""
    return {
        "status": "ok",
        "service": "ping_me",
        "configured": bool(BOT_TOKEN and CHAT_ID),
        "secret_required": bool(PING_SECRET),
    }


@app.get("/ping")
def ping(
    request: Request,
    msg: Optional[str] = Query(default=None, description="Custom message text."),
    key: str = Query(default="", description="Secret key, required if PING_SECRET is set."),
):
    """Trigger a Telegram ping. This is the URL you expose to the internet."""
    if PING_SECRET and key != PING_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing key.")

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    # Real client IP, even behind ngrok / Cloudflare / a reverse proxy.
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    elif request.client:
        client_ip = request.client.host
    else:
        client_ip = "unknown"

    text = msg or f"\U0001F514 Ping!\nYour endpoint was hit.\n\U0001F552 {now}\n\U0001F310 from {client_ip}"
    send_telegram(text)
    return {"ok": True, "sent": text}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

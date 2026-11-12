"""
ping_me - a tiny GET API that pings your phone over Telegram.

Hit  GET /ping  and you get a Telegram message.

Optional query params on /ping:
  ?msg=Custom text   -> send your own text instead of the default
  ?key=SECRET        -> required only when PING_SECRET is set (keeps strangers out)
  ?call=1            -> also ring your phone with a Telegram voice call
                        (needs CALLMEBOT_USER, see README)
"""

import html
import os
import re
import time
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


def _normalize_call_user(raw: str) -> str:
    """Turn '+91 98765-43210', '919876543210', 'name' or '@name' into what CallMeBot expects."""
    raw = raw.strip()
    if not raw or raw.startswith("@"):
        return raw
    if re.fullmatch(r"[+\d\s().-]+", raw):
        digits = re.sub(r"\D", "", raw)
        return "+" + digits if digits else ""
    return "@" + raw


BOT_TOKEN = "".join(os.getenv("TELEGRAM_BOT_TOKEN", "").split())
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
PING_SECRET = os.getenv("PING_SECRET", "").strip()  # optional
CALLMEBOT_USER = _normalize_call_user(os.getenv("CALLMEBOT_USER", ""))  # optional

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
CALLMEBOT_URL = "https://api.callmebot.com/start.php"
DEFAULT_CALL_TEXT = "Ping. Your endpoint was hit."

app = FastAPI(
    title="ping_me",
    description="Hit the endpoint, get a Telegram ping on your phone.",
    version="1.1.0",
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
    except requests.RequestException:
        raise HTTPException(
            status_code=502,
            detail="Could not reach Telegram. Check your internet connection and try again.",
        ) from None
    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Telegram API error: {resp.text}")


def _visible_text(page: bytes) -> str:
    """Reduce an HTML reply, possibly cut off mid-tag, to its readable text."""
    text = page.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?is)<script.*$", " ", text)  # script cut off by a partial read
    text = re.sub(r"(?i)</?(?:b|i|u|a|em|strong|span|font)\b[^>]*>", "", text)  # inline tags: no gap
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"<[^>]*$", " ", text)  # tag cut off by a partial read
    return " ".join(html.unescape(text).split())


def place_call(text: str) -> dict:
    """Ask CallMeBot to ring CALLMEBOT_USER on Telegram and speak `text`.

    Never raises: the Telegram message is already sent when this runs, so a
    failed call is reported in the response instead of failing the whole ping.
    """
    if not CALLMEBOT_USER:
        return {"requested": False, "error": "CALLMEBOT_USER is not set on the server."}

    params = {
        "user": CALLMEBOT_USER,
        "text": text,
        "rpt": 2,
        "cc": "no",  # the bot message is already the text copy
    }
    page = b""
    try:
        # Refusals (unknown user, not authorized) come back as a complete page
        # within a few seconds. A real call may keep the connection open while
        # the phone rings, so wait a bounded time and then hang up.
        with requests.get(CALLMEBOT_URL, params=params, stream=True, timeout=(4, 6)) as resp:
            if resp.status_code >= 400:
                return {
                    "requested": False,
                    "error": f"CallMeBot returned HTTP {resp.status_code}. "
                    "It may be busy or limiting repeated requests; try again shortly.",
                }
            deadline = time.monotonic() + 3
            try:
                for chunk in resp.iter_content(chunk_size=256):
                    page += chunk
                    if len(page) > 16384 or time.monotonic() > deadline:
                        break
            except requests.RequestException:
                pass  # it stopped answering mid-reply; judge by what arrived
    except requests.ReadTimeout:
        return {"requested": True, "reply": "No refusal from CallMeBot after 6 seconds, so the call should be on its way."}
    except requests.RequestException:
        return {"requested": False, "error": "Could not reach CallMeBot."}

    reply = _visible_text(page)[:300]
    low = reply.lower()
    if "not authorized" in low:
        return {
            "requested": False,
            "error": reply + " To authorize: in Telegram, send /start to @CallMeBot_txtbot.",
        }
    if low.startswith("error") or "error:" in low or "calls disabled" in low:
        return {"requested": False, "error": reply}
    return {"requested": True, "reply": reply or "CallMeBot accepted the request."}


@app.get("/")
def health():
    """Health check - confirms the service is up and configured."""
    return {
        "status": "ok",
        "service": "ping_me",
        "configured": bool(BOT_TOKEN and CHAT_ID),
        "secret_required": bool(PING_SECRET),
        "call_configured": bool(CALLMEBOT_USER),
    }


@app.get("/ping")
def ping(
    request: Request,
    msg: Optional[str] = Query(default=None, description="Custom message text."),
    key: str = Query(default="", description="Secret key, required if PING_SECRET is set."),
    call: bool = Query(default=False, description="Also ring the phone with a Telegram voice call."),
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

    result = {"ok": True, "sent": text}
    if call:
        # Spoken text: no emoji or line breaks, and CallMeBot cuts it at 256 characters.
        result["call"] = place_call(" ".join((msg or DEFAULT_CALL_TEXT).split())[:256])
    return result


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

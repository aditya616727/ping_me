"""
ping_me - a tiny GET API that pings your phone over Telegram.

Hit  GET /ping  and you get a Telegram message.

Optional query params on /ping:
  ?msg=Custom text   -> send your own text instead of the default
  ?key=SECRET        -> required only when PING_SECRET is set (keeps strangers out)
  ?call=1            -> also ring your phone with a Telegram voice call
                        (needs CALLMEBOT_USER, see README)
  ?alarm=0           -> skip the urgent ntfy alert, which is otherwise sent
                        with every ping once NTFY_TOPIC is set (see README)
"""

import html
import mimetypes
import os
import re
import smtplib
import ssl
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional
from urllib.parse import quote, unquote

import requests
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import EmailStr, TypeAdapter, ValidationError

# Load variables from a local .env file, if python-dotenv is installed.
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass


def _normalize_call_user(raw: str) -> str:
    """Turn '+91 98765-43210', '919876543210', '%2B919876543210', 'name' or '@name'
    into what CallMeBot expects."""
    raw = unquote(raw).strip()  # tolerate a value pasted in URL-encoded form
    if not raw or raw.startswith("@"):
        return raw
    if re.fullmatch(r"[+\d\s().-]+", raw):
        digits = re.sub(r"\D", "", raw)
        return "+" + digits if digits else ""
    return "@" + raw


def _normalize_topic(raw: str) -> str:
    """Accept 'mytopic', 'ntfy.sh/mytopic' or 'https://ntfy.sh/mytopic'."""
    return unquote(raw).strip().rstrip("/").rsplit("/", 1)[-1]


BOT_TOKEN = "".join(os.getenv("TELEGRAM_BOT_TOKEN", "").split())
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
PING_SECRET = os.getenv("PING_SECRET", "").strip()  # optional
CALLMEBOT_USER = _normalize_call_user(os.getenv("CALLMEBOT_USER", ""))  # optional
NTFY_TOPIC = _normalize_topic(os.getenv("NTFY_TOPIC", ""))  # optional
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = os.getenv("SMTP_PORT", "587").strip()
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "").strip() or SMTP_USERNAME
SMTP_SECURITY = os.getenv("SMTP_SECURITY", "starttls").strip().lower()
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
CALLMEBOT_URL = "https://api.callmebot.com/start.php"
NTFY_URL = "https://ntfy.sh/"
DEFAULT_CALL_TEXT = "Ping. Your endpoint was hit."

app = FastAPI(
    title="ping_me",
    description="Send Telegram pings and email with document attachments over SMTP.",
    version="1.3.0",
)


def send_email(message: EmailMessage) -> None:
    """Submit a message to the configured SMTP server over TLS."""
    if not SMTP_HOST or not SMTP_FROM:
        raise HTTPException(
            status_code=500,
            detail="Server not configured: set SMTP_HOST and SMTP_FROM (or SMTP_USERNAME).",
        )
    try:
        port = int(SMTP_PORT)
        if not 1 <= port <= 65535 or SMTP_SECURITY not in {"starttls", "ssl"}:
            raise ValueError
        sender = str(TypeAdapter(EmailStr).validate_python(SMTP_FROM))
    except (ValueError, ValidationError):
        raise HTTPException(
            status_code=500,
            detail="Invalid SMTP configuration: check SMTP_PORT, SMTP_FROM and SMTP_SECURITY (starttls or ssl).",
        ) from None
    if bool(SMTP_USERNAME) != bool(SMTP_PASSWORD):
        raise HTTPException(
            status_code=500,
            detail="Set both SMTP_USERNAME and SMTP_PASSWORD for SMTP authentication.",
        )

    message["From"] = sender
    context = ssl.create_default_context()
    try:
        if SMTP_SECURITY == "ssl":
            client = smtplib.SMTP_SSL(SMTP_HOST, port, timeout=15, context=context)
        else:
            client = smtplib.SMTP(SMTP_HOST, port, timeout=15)
        with client:
            if SMTP_SECURITY == "starttls":
                client.starttls(context=context)
            if SMTP_USERNAME:
                client.login(SMTP_USERNAME, SMTP_PASSWORD)
            client.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise HTTPException(status_code=502, detail="SMTP authentication failed. Check the server credentials.") from None
    except smtplib.SMTPRecipientsRefused:
        raise HTTPException(status_code=502, detail="The SMTP server rejected the recipient.") from None
    except (smtplib.SMTPException, OSError):
        raise HTTPException(status_code=502, detail="Could not send email through the SMTP server.") from None


@app.post("/email")
def email(
    to: EmailStr = Form(description="Recipient email address."),
    subject: str = Form(min_length=1, max_length=998),
    body: str = Form(default="", max_length=100000),
    attachments: Optional[list[UploadFile]] = File(
        default=None, description="Optional document uploads, up to 10 MiB combined."
    ),
    key: str = Query(default="", description="Secret key, required if PING_SECRET is set."),
):
    """Send an email, optionally with one or more document attachments."""
    if PING_SECRET and key != PING_SECRET:
        raise HTTPException(status_code=401, detail="Invalid or missing key.")
    if "\r" in subject or "\n" in subject:
        raise HTTPException(status_code=422, detail="Subject must be a single line.")

    message = EmailMessage()
    message["To"] = str(to)
    message["Subject"] = subject
    message.set_content(body)
    filenames = []
    total_bytes = 0
    for attachment in attachments or []:
        filename = (attachment.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not filename or any(ord(char) < 32 or ord(char) == 127 for char in filename):
            raise HTTPException(status_code=422, detail="Each attachment needs a valid filename.")
        data = attachment.file.read(MAX_ATTACHMENT_BYTES - total_bytes + 1)
        total_bytes += len(data)
        if total_bytes > MAX_ATTACHMENT_BYTES:
            raise HTTPException(status_code=413, detail="Attachments exceed the combined 10 MiB limit.")
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        maintype, subtype = content_type.split("/", 1)
        message.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)
        filenames.append(filename)

    send_email(message)
    return {"ok": True, "to": str(to), "subject": subject, "attachments": filenames}


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


def send_alarm(text: str) -> dict:
    """Publish `text` as an urgent notification to the ntfy topic NTFY_TOPIC.

    Never raises, so a failed alert is reported in the response instead of
    failing the ping.
    """
    if not NTFY_TOPIC:
        return {"sent": False, "error": "NTFY_TOPIC is not set on the server."}
    if not re.fullmatch(r"[-_A-Za-z0-9]{1,64}", NTFY_TOPIC):
        return {
            "sent": False,
            "error": "NTFY_TOPIC is not a valid ntfy topic name (letters, digits, - and _ only).",
        }
    try:
        resp = requests.post(
            NTFY_URL,
            json={"topic": NTFY_TOPIC, "title": "Ping", "message": text, "priority": 5, "tags": ["bell"]},
            timeout=(4, 6),
        )
    except requests.RequestException:
        return {"sent": False, "error": "Could not reach ntfy."}
    if resp.status_code != 200:
        return {"sent": False, "error": f"ntfy returned HTTP {resp.status_code}."}
    return {"sent": True}


def _visible_text(page: bytes) -> str:
    """Reduce an HTML reply, possibly cut off mid-tag, to its readable text."""
    text = page.decode("utf-8", errors="replace")
    text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?is)<script.*$", " ", text)  # script cut off by a partial read
    text = re.sub(r"(?i)</?(?:b|i|u|a|em|strong|span|font)\b[^>]*>", "", text)  # inline tags: no gap
    text = re.sub(r"<[^>]*>", " ", text)
    text = re.sub(r"<[^>]*$", " ", text)  # tag cut off by a partial read
    return " ".join(html.unescape(text).split())


def _hide_user(text: str) -> str:
    """Keep the configured phone number or username out of API responses."""
    core = CALLMEBOT_USER.lstrip("+@")
    for needle in (CALLMEBOT_USER, quote(CALLMEBOT_USER, safe=""), core):
        if len(needle) >= 5:
            text = re.sub(re.escape(needle), "[hidden]", text, flags=re.IGNORECASE)
    # Also covers a number cut off by a partial read, and Telegram user IDs.
    return re.sub(r"\+?\d{7,}", "[hidden]", text)


def place_call(text: str) -> dict:
    """Ask CallMeBot to ring CALLMEBOT_USER on Telegram and speak `text`.

    Never raises: the Telegram message is already sent when this runs, so a
    failed call is reported in the response instead of failing the whole ping.
    """
    if not CALLMEBOT_USER:
        return {"requested": False, "error": "CALLMEBOT_USER is not set on the server."}

    # The query string is built by hand because CallMeBot rejects a phone number
    # whose plus sign is percent-encoded ("%2B..." -> "wrong format"); it must be
    # a literal "+". cc=no: the bot message is already the text copy.
    url = (
        f"{CALLMEBOT_URL}?user={quote(CALLMEBOT_USER, safe='+@')}"
        f"&text={quote(text, safe='')}&rpt=2&cc=no"
    )
    page = b""
    try:
        # Refusals (unknown user, not authorized) come back as a complete page,
        # after up to about 10 seconds for a phone number. A real call may keep
        # the connection open while the phone rings, so wait a bounded time and
        # then hang up.
        with requests.get(url, stream=True, timeout=(4, 12)) as resp:
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
        return {"requested": True, "reply": "No refusal from CallMeBot after 12 seconds, so the call should be on its way."}
    except requests.RequestException:
        return {"requested": False, "error": "Could not reach CallMeBot."}

    seen = _hide_user(_visible_text(page))
    low = seen.lower()
    # CallMeBot puts its explanation of a failure after "Error:" or "Warning!",
    # behind a long progress log, so report from there rather than from the top.
    starts = [at for at in (low.find("error:"), low.find("warning!")) if at != -1]
    if starts or "not authorized" in low or "calls disabled" in low:
        problem = seen[min(starts):][:300] if starts else seen[:300]
        if "not authorized" in low:
            problem += " To authorize: in Telegram, send /start to @CallMeBot_txtbot."
        return {"requested": False, "error": problem}
    return {"requested": True, "reply": seen[-300:] or "CallMeBot accepted the request."}


@app.get("/")
def health():
    """Health check - confirms the service is up and configured."""
    return {
        "status": "ok",
        "service": "ping_me",
        "version": app.version,
        "configured": bool(BOT_TOKEN and CHAT_ID),
        "secret_required": bool(PING_SECRET),
        "call_configured": bool(CALLMEBOT_USER),
        "alarm_configured": bool(NTFY_TOPIC),
        "email_configured": bool(SMTP_HOST and SMTP_FROM),
    }


@app.get("/ping")
def ping(
    request: Request,
    msg: Optional[str] = Query(default=None, description="Custom message text."),
    key: str = Query(default="", description="Secret key, required if PING_SECRET is set."),
    call: bool = Query(default=False, description="Also ring the phone with a Telegram voice call."),
    alarm: Optional[bool] = Query(
        default=None,
        description="Urgent alert through ntfy. Sent by default once NTFY_TOPIC is set; alarm=0 skips it.",
    ),
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
    want_alarm = alarm if alarm is not None else bool(NTFY_TOPIC)
    try:
        send_telegram(text)
    except HTTPException:
        if want_alarm:
            send_alarm(text)  # Telegram failed, so the second channel matters most now
        raise

    result = {"ok": True, "sent": text}
    if want_alarm:
        result["alarm"] = send_alarm(text)
    if call:
        # Spoken text: no emoji or line breaks, and CallMeBot cuts it at 256 characters.
        result["call"] = place_call(" ".join((msg or DEFAULT_CALL_TEXT).split())[:256])
    return result


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

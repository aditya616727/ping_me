# ping_me

A tiny GET API: **hit a URL, get a Telegram message on your phone.**

```
GET https://your-url/ping   ->   🔔 Telegram ping
```

Trigger it from anywhere — a browser bookmark, a webhook, a cron job, an uptime
monitor, an IoT device. Telegram is free, instant, needs no approval, and works
worldwide.

---

## 1. Create a Telegram bot  (~1 min)

1. Open Telegram and search for **@BotFather**.
2. Send `/newbot`, pick a name and a username.
3. BotFather replies with a **token** like `123456789:AAH...`. Keep it.

## 2. Get your chat ID  (~1 min)

1. Tap the `t.me/<your_bot>` link BotFather gave you and send the bot any
   message (e.g. `hi`). *(The bot can only message you after you message it first.)*
2. Copy `.env.example` to `.env` and paste your **complete** token into
   `TELEGRAM_BOT_TOKEN`, including the numeric ID and colon, with no spaces.
   Put real credentials in `.env`; keep `.env.example` as a template.
3. Run the helper — it prints your chat ID:

   ```bash
   python get_chat_id.py
   ```

4. Put that number into `TELEGRAM_CHAT_ID` in `.env`.

## 3. Install & run

PowerShell (Windows):

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

The server runs at `http://localhost:8000`.

- Test it: open **http://localhost:8000/ping** in your browser → you should get a
  Telegram message within a second.
- Interactive docs / try-it button: **http://localhost:8000/docs**

## 4. Expose it to the internet

Pick one:

- **ngrok** (quickest): install it, then run `ngrok http 8000`. You get a public
  URL like `https://abc123.ngrok-free.app`. Your endpoint is
  `https://abc123.ngrok-free.app/ping`.
- **Cloudflare Tunnel** (free, no account for a quick tunnel):
  `cloudflared tunnel --url http://localhost:8000`.
- **Deploy it 24/7** (so your PC doesn't need to stay on): see
  [Deploy for 24/7](#deploy-for-247-no-pc-needed) below - Vercel, Render, or Railway.

## 5. Lock it down  (recommended once the URL is public)

Anyone who finds your URL can ping you. Set a secret in `.env`:

```
PING_SECRET=some-long-random-string
```

Restart the server. Now `/ping` requires the key:

```
GET /ping?key=some-long-random-string
```

Calls without the right key get `401 Unauthorized`.

---

## Deploy for 24/7 (no PC needed)

This repo ships ready-to-deploy configs. On whichever host you pick, set these three
environment variables (never commit the real values): `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, and `PING_SECRET`.

Most hosts deploy from a GitHub repo, so push this folder first:

```bash
git init
git add .
git commit -m "ping_me"
```

Create a repo on GitHub and push to it, then connect it on one of these:

### Vercel (serverless - great fit)

File: `vercel.json` (it serves `main.py` directly). Scales to zero with only short cold starts
(no 30-60s wake-up like free Render). Deploy from GitHub, or straight from this
folder with the CLI:

```bash
npm i -g vercel
vercel
```

Add the env vars under **Project -> Settings -> Environment Variables**, then
redeploy. Endpoint: `https://<project>.vercel.app/ping`.

### Render (Docker)

File: `render.yaml`. In Render: **New + -> Blueprint**, connect the repo. Render
builds the `Dockerfile` and prompts for the three env vars. Endpoint:
`https://<name>.onrender.com/ping`.

> Note: Render's free web service sleeps after ~15 min idle, so the first ping after
> a quiet spell can take ~30-60s to wake. Vercel or a paid instance avoids this.

### Railway (Docker)

Files: `Dockerfile` + `Procfile`. In Railway: **New Project -> Deploy from GitHub**,
pick the repo, and add the env vars under **Variables**. Railway builds the
Dockerfile and gives you a public URL.

### Any Docker host / your own server

```bash
docker build -t ping-me .
docker run -p 8000:8000 -e TELEGRAM_BOT_TOKEN=xxx -e TELEGRAM_CHAT_ID=xxx -e PING_SECRET=xxx ping-me
```

---

## Customizing the message

Send your own text with `?msg=`:

```
GET /ping?msg=Server%20is%20down
GET /ping?key=SECRET&msg=Backup%20finished
```

With no `msg`, the default includes the time and the caller's IP address.

## Alarm-style alert (optional, free)

For an alert that is hard to miss, the API can also publish each ping as an urgent
notification through [ntfy](https://ntfy.sh), a free push service with apps for
Android and iPhone. It is not a voice call: the phone plays the notification sound,
vibrates and shows a pop-over.

1. Install the **ntfy** app on your phone.
2. Pick a topic name that nobody could guess (letters, digits, `-` and `_`). Topics
   on ntfy.sh are public: anyone who knows the name can read and send your alerts,
   so treat it like a password.
3. In the app, subscribe to that topic.
4. Set `NTFY_TOPIC` to the topic name, in `.env` or in your host's environment
   variables, then restart or redeploy.

From then on every `/ping` also sends the alert, and the response has an `alarm`
field. Add `alarm=0` to a URL to skip the alert for that request. `GET /` reports
`alarm_configured`. If Telegram cannot be reached, the alert is still sent.

On Android, each priority has its own notification channel. In the app's channel
settings for the highest priority you can pick a long sound and let it override
Do Not Disturb.

## Ring your phone too (optional)

A Telegram bot can only send messages; it cannot place calls. To make `/ping` also
ring your phone, this API can ask [CallMeBot](https://www.callmebot.com/telegram-call-api/),
a third-party service, to place a Telegram voice call that reads the message aloud.

1. In Telegram, search for **@CallMeBot_txtbot** and press **Start** to authorize it.
2. In Telegram **Settings -> Privacy and Security -> Calls**, allow calls from everybody.
3. Set `CALLMEBOT_USER` to your Telegram phone number with country code (for example
   `+14155550123`) or your `@username`. Put it in `.env`, or in your host's environment
   variables, then restart or redeploy.
4. Add `call=1` to the URL:

```
GET /ping?key=SECRET&call=1
GET /ping?key=SECRET&call=1&msg=Server%20is%20down
```

The Telegram message is always sent first. The response then has a `call` field that
says whether the call was requested and what CallMeBot replied. `GET /` reports
`call_configured` so you can check the variable reached the server.

Things to know:

- Your number and the spoken text pass through CallMeBot, and the call comes from
  their account.
- On the free shared service, calls last about 30 seconds, the text is cut at 256
  characters, and calls can be delayed.
- Requests sent in quick succession can be refused; the `call` field then reports
  `HTTP 503`.
- If the `call` field says CallMeBot was reported as a spammer, Telegram is limiting
  the account it calls from. Its reply names that account (for example
  `@CallMeBot_API16`); add it to your Telegram contacts and send it a message, then
  try again.
- On iPhone the call rings but may not play the spoken text (a Telegram bug).

## Endpoints

| Method & path | What it does |
| --- | --- |
| `GET /`      | Health check — is the service up and configured? |
| `GET /ping`  | Sends the Telegram ping. **This is the URL you expose.** Also sends the ntfy alert once `NTFY_TOPIC` is set. Add `call=1` to ring the phone too. |
| `GET /docs`  | Interactive API docs (Swagger UI). |

## Files

| File | Purpose |
| --- | --- |
| `main.py`          | The API server. |
| `get_chat_id.py`   | One-off helper to find your Telegram chat ID. |
| `.env.example`     | Copy to `.env` and fill in your values. |
| `requirements.txt` | Python dependencies. |

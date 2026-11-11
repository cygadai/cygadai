# CYGAD AI — IoT & Embedded Systems Assistant

This starter project gives you:
- One FastAPI backend for the website/PWA and Telegram.
- Gemini first, Groq fallback, and optional local Ollama.
- SQLite conversation history.
- A mobile-friendly installable website (PWA).
- Optional Telegram bot using long polling.

## Important limitations

- Gemini and Groq need internet and have provider-specific quotas. Free access is not unlimited.
- Offline mode works only when this backend and Ollama are running on a computer on your local network (or on that same computer).
- Telegram requires internet, even if the local AI is used.
- The PWA caches its interface, not the AI model or chat API. It cannot generate answers offline unless it can reach your local backend and Ollama.
- WhatsApp is not included in this first build. It requires a Meta WhatsApp Business Cloud API setup and webhook; we can add it as a separate integration.
- A free cloud host may sleep, restart or have temporary storage. SQLite on a free ephemeral host may be lost. Use a persistent database/storage before relying on it for long-term memory.

## 1. Get API keys

1. Gemini: https://aistudio.google.com/app/apikey
2. Groq: https://console.groq.com/keys
3. Telegram (optional): open Telegram, message `@BotFather`, use `/newbot`, and copy the token.

Never paste API keys into public code or GitHub. Keep them in `.env` or your host's secret/environment settings.

## 2. Install Python

Install 64-bit Python 3.11 or newer from https://www.python.org/downloads/.
On Windows, tick **Add Python to PATH** during installation.

Open Command Prompt in this project folder:

```bash
python -m venv .venv
```

Windows:
```bat
.venv\Scripts\activate
```

Linux/macOS:
```bash
source .venv/bin/activate
```

Install dependencies:
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## 3. Configure the keys

Copy `.env.example` to `.env`.

Windows:
```bat
copy .env.example .env
```

Linux/macOS:
```bash
cp .env.example .env
```

Open `.env` with a text editor and fill in `GEMINI_API_KEY` and `GROQ_API_KEY`.
For a public deployment, set a long unique `APP_PASSWORD`.
For private Telegram access, put your Telegram numeric user ID in `TELEGRAM_ALLOWED_USER_IDS`.

## 4. Start the app

```bash
uvicorn app:app --host 0.0.0.0 --port 8000
```

On the same computer open:
http://127.0.0.1:8000

Check:
http://127.0.0.1:8000/health

In the web app choose **Automatic**. It tries Gemini, then Groq, then Ollama.

## 5. Set up offline AI with Ollama

Install Ollama from https://ollama.com/download.

Then download a small model:
```bash
ollama pull qwen2.5:0.5b
```

Test it:
```bash
ollama run qwen2.5:0.5b
```

Keep Ollama running. Set these in `.env`:
```env
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen2.5:0.5b
```

Restart CYGAD AI and select **Offline / Ollama only**.

A 1.5B model is small and may be less capable. The download needs internet once. After download, local inference can run without internet. On a computer with only 4 GB RAM, even this may be slow or fail; close other apps and test carefully. A 64-bit OS is recommended.

## 6. Telegram setup

1. Create a bot using `@BotFather` and copy its token.
2. Put the token in `.env` as `TELEGRAM_BOT_TOKEN`.
3. Find your numeric Telegram user ID using a trusted ID bot, then set `TELEGRAM_ALLOWED_USER_IDS` to that number.
4. Restart CYGAD AI.
5. Open your new Telegram bot and send `/start`.

The bot uses long polling. Do not run two copies of this same bot at the same time. If you previously configured a webhook, this app removes it because long polling and webhooks cannot run together.

## 7. Use it on your Android phone

For installation as an app:
1. Deploy the web app to an HTTPS host.
2. Open its HTTPS address in Chrome on Android.
3. Open Chrome's menu and choose **Install app** or **Add to Home screen**.
4. Sign in with your app password if you configured one.

For local-network use, run the backend on your computer and open `http://COMPUTER-LAN-IP:8000` from a phone on the same Wi-Fi. This is for trusted local networks only; the PWA install prompt may require HTTPS.

## 8. Deploy online (Render example)

1. Push this project to a private GitHub repository.
2. Create a Render account and create a new Web Service from that repository.
3. Select the Docker runtime (Render can detect the included Dockerfile).
4. Add environment variables in Render: `GEMINI_API_KEY`, `GROQ_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS`, and a strong `APP_PASSWORD`.
5. Deploy and open the HTTPS URL.

Free web services can sleep after inactivity and have limited resources. Telegram polling may stop while the service sleeps. Free local filesystem storage may be temporary, so do not treat the included SQLite database as permanent cloud storage. For dependable long-term operation, use a host with always-on service and persistent storage or a managed database.

## 9. Security checklist

- Do not commit `.env` or API keys to GitHub.
- Use a strong `APP_PASSWORD` on any public deployment.
- Set `TELEGRAM_ALLOWED_USER_IDS` for a private bot.
- Do not expose Ollama's port 11434 to the public internet.
- Do not use this starter as a multi-user public service without proper accounts, rate limiting, abuse protection and persistent database storage.
- Never let AI-generated code directly control dangerous machinery without independent checks and human supervision.

## Troubleshooting

- `GEMINI_API_KEY is not configured`: check `.env` spelling and restart the app.
- Gemini 429/quota: wait for quota reset or let Automatic mode try Groq.
- Groq model error: check the current active model list in https://console.groq.com/docs/models and update `GROQ_MODEL`.
- Ollama connection error: open a terminal and run `ollama list`; make sure the Ollama service is running and model is downloaded.
- Telegram not replying: check token, user ID allowlist, internet, and ensure only one bot polling process is running.
- Port already in use: change `--port 8000` to another port such as `--port 8001`.

## Next development phases

1. Image uploads and circuit/photo analysis.
2. WhatsApp Business Cloud API webhook.
3. User accounts, safer persistent database, rate limits and admin dashboard.
4. Project library / searchable IoT learning resources.
5. Optional ESP32 device control through MQTT with authentication and safety interlocks.

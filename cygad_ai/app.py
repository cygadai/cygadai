import asyncio
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = os.getenv("DATABASE_PATH", str(ROOT / "cygad_ai.db"))

SYSTEM_PROMPT = """
You are CYGAD AI, a patient and practical tutor specializing in IoT,
embedded systems, electronics, microcontrollers and programming.

Main subjects: Arduino, ESP32, ESP8266, Raspberry Pi, sensors, actuators,
GPIO, UART, I2C, SPI, PWM, Wi-Fi, Bluetooth, MQTT, HTTP, Telegram bots,
Python, C/C++, PHP, JavaScript, databases, PCB design and debugging.

Teach step by step. Explain unfamiliar terms simply. When writing code:
- provide complete, compilable examples where practical;
- state the board, libraries, wiring and pin assumptions;
- explain where each code section belongs;
- warn about voltage, current, mains electricity and other hazards;
- never claim code was tested on physical hardware unless it was;
- ask for the exact board, error message or circuit photo when essential.
For project ideas, include objectives, components, block diagram description,
working principle, implementation steps, testing and possible improvements.
Support English, French and Kinyarwanda. Reply in the language the user uses.
Do not invent datasheet specifications. Say when a detail needs verification.
"""

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_key TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_messages_user_id ON messages(user_key, id)")

def save_message(user_key: str, role: str, content: str):
    with db() as con:
        con.execute(
            "INSERT INTO messages(user_key, role, content, created_at) VALUES(?,?,?,?)",
            (user_key, role, content, datetime.now(timezone.utc).isoformat())
        )

def get_history(user_key: str, limit: int = 12):
    with db() as con:
        rows = con.execute(
            "SELECT role, content FROM messages WHERE user_key=? ORDER BY id DESC LIMIT ?",
            (user_key, limit)
        ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

def clear_history(user_key: str):
    with db() as con:
        con.execute("DELETE FROM messages WHERE user_key=?", (user_key,))

def check_password(password: Optional[str]):
    required = os.getenv("APP_PASSWORD", "")
    if required and password != required:
        raise HTTPException(status_code=401, detail="Incorrect app password.")

def messages_for_prompt(history, new_message):
    items = [{"role": "system", "content": SYSTEM_PROMPT}]
    items.extend(history)
    items.append({"role": "user", "content": new_message})
    return items

async def ask_gemini(history, prompt):
    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")
    client = genai.Client(api_key=key)
    transcript = []
    for item in history[-10:]:
        label = "User" if item["role"] == "user" else "CYGAD AI"
        transcript.append(f"{label}: {item['content']}")
    transcript.append(f"User: {prompt}")
    response = await asyncio.to_thread(
        client.models.generate_content,
        model=os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        contents="\n\n".join(transcript),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            temperature=0.5,
            max_output_tokens=1800
        )
    )
    answer = getattr(response, "text", None)
    if not answer:
        raise RuntimeError("Gemini returned an empty response.")
    return answer.strip()

async def ask_groq(history, prompt):
    from groq import Groq

    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured.")
    client = Groq(api_key=key)
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    msgs.extend(history[-10:])
    msgs.append({"role": "user", "content": prompt})
    result = await asyncio.to_thread(
        client.chat.completions.create,
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        messages=msgs,
        temperature=0.5,
        max_tokens=1800
    )
    answer = result.choices[0].message.content
    if not answer:
        raise RuntimeError("Groq returned an empty response.")
    return answer.strip()

async def ask_ollama(history, prompt):
    url = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    msgs.extend(history[-8:])
    msgs.append({"role": "user", "content": prompt})
    async with httpx.AsyncClient(timeout=180) as client:
        response = await client.post(
            f"{url}/api/chat",
            json={"model": model, "messages": msgs, "stream": False}
        )
        response.raise_for_status()
        data = response.json()
    answer = data.get("message", {}).get("content", "")
    if not answer:
        raise RuntimeError("Ollama returned an empty response.")
    return answer.strip()

async def generate_reply(user_key, prompt, requested_provider="AUTO"):
    history = get_history(user_key)
    mode = (requested_provider or "AUTO").upper()
    attempts = []

    if mode == "GEMINI":
        order = ["GEMINI"]
    elif mode == "GROQ":
        order = ["GROQ"]
    elif mode == "LOCAL":
        order = ["LOCAL"]
    else:
        order = ["GEMINI", "GROQ", "LOCAL"]

    for provider in order:
        try:
            if provider == "GEMINI":
                answer = await ask_gemini(history, prompt)
                actual = "Gemini"
            elif provider == "GROQ":
                answer = await ask_groq(history, prompt)
                actual = "Groq"
            else:
                answer = await ask_ollama(history, prompt)
                actual = "Ollama (offline/local)"
            save_message(user_key, "user", prompt)
            save_message(user_key, "assistant", answer)
            return answer, actual
        except Exception as exc:
            attempts.append(f"{provider}: {str(exc)[:180]}")

    detail = " | ".join(attempts) if attempts else "No provider configured."
    raise RuntimeError(
        "CYGAD AI could not reach an available AI provider. "
        "Check your API keys, internet connection, model name, or Ollama status. "
        + detail
    )

class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(min_length=8, max_length=100)
    provider: str = Field(default="AUTO", pattern="^(AUTO|GEMINI|GROQ|LOCAL)$")

class ClearRequest(BaseModel):
    session_id: str = Field(min_length=8, max_length=100)

telegram_task = None
telegram_stop = asyncio.Event()

async def telegram_send(client, token, chat_id, text):
    # Telegram message limit is 4096 characters; split safely below it.
    chunks = [text[i:i+3900] for i in range(0, len(text), 3900)] or [" "]
    for chunk in chunks:
        await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": chunk}
        )

async def telegram_loop():
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return
    allowed_raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
    allowed = {x.strip() for x in allowed_raw.split(",") if x.strip()}
    offset = None
    async with httpx.AsyncClient(timeout=40) as client:
        # Long polling and webhooks cannot be used at the same time.
        try:
            await client.post(f"https://api.telegram.org/bot{token}/deleteWebhook",
                              json={"drop_pending_updates": False})
        except Exception:
            pass
        while not telegram_stop.is_set():
            try:
                params = {"timeout": 25}
                if offset is not None:
                    params["offset"] = offset
                response = await client.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params=params,
                    timeout=35
                )
                response.raise_for_status()
                data = response.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    msg = update.get("message") or update.get("edited_message")
                    if not msg or not msg.get("text"):
                        continue
                    chat_id = msg["chat"]["id"]
                    sender_id = str(msg.get("from", {}).get("id", ""))
                    text = msg["text"].strip()
                    if allowed and sender_id not in allowed:
                        await telegram_send(client, token, chat_id, "Sorry, this bot is private.")
                        continue
                    user_key = f"telegram:{chat_id}"
                    if text.startswith("/start") or text.startswith("/help"):
                        await telegram_send(client, token, chat_id,
                            "Welcome to CYGAD AI! Ask me about IoT, ESP32, Arduino, electronics or programming.\n"
                            "Commands: /reset clears this chat's AI history.")
                        continue
                    if text.startswith("/reset"):
                        clear_history(user_key)
                        await telegram_send(client, token, chat_id, "Your CYGAD AI chat history has been cleared.")
                        continue
                    try:
                        answer, used = await generate_reply(user_key, text, "AUTO")
                        await telegram_send(client, token, chat_id, f"{answer}\n\n— {used}")
                    except Exception as exc:
                        await telegram_send(client, token, chat_id, f"AI error: {str(exc)[:900]}")
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(5)

@asynccontextmanager
async def lifespan(app: FastAPI):
    global telegram_task
    init_db()
    if os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        telegram_stop.clear()
        telegram_task = asyncio.create_task(telegram_loop())
    yield
    telegram_stop.set()
    if telegram_task:
        telegram_task.cancel()
        try:
            await telegram_task
        except asyncio.CancelledError:
            pass

app = FastAPI(title="CYGAD AI", version="1.0.0", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

@app.get("/")
async def home():
    return FileResponse(STATIC / "index.html")

@app.get("/manifest.json")
async def manifest():
    return FileResponse(STATIC / "manifest.json", media_type="application/manifest+json")

@app.get("/sw.js")
async def service_worker():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript")

@app.get("/health")
async def health():
    return {
        "ok": True,
        "gemini_configured": bool(os.getenv("GEMINI_API_KEY")),
        "groq_configured": bool(os.getenv("GROQ_API_KEY")),
        "telegram_configured": bool(os.getenv("TELEGRAM_BOT_TOKEN")),
        "local_model": os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b")
    }

@app.post("/api/chat")
async def chat(request: ChatRequest, x_app_password: Optional[str] = Header(default=None)):
    check_password(x_app_password)
    try:
        answer, provider = await generate_reply(
            f"web:{request.session_id}", request.message, request.provider
        )
        return {"answer": answer, "provider": provider}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

@app.post("/api/clear")
async def clear(request: ClearRequest, x_app_password: Optional[str] = Header(default=None)):
    check_password(x_app_password)
    clear_history(f"web:{request.session_id}")
    return {"ok": True}

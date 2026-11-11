
import asyncio
import logging
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

# ============================================================
# 1. APPLICATION CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = os.getenv("DATABASE_PATH", str(ROOT / "cygad_ai.db"))

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)

logger = logging.getLogger("cygad_ai")


# ============================================================
# 2. CYGAD AI SYSTEM PROMPT
# ============================================================

SYSTEM_PROMPT = """
You are CYGAD AI, an advanced, friendly engineering assistant
specialized in IoT, embedded systems, electronics and programming.

IDENTITY:
- Speak naturally, clearly and confidently.
- Be practical, intelligent, patient and professional.
- Never describe yourself as merely a text-based tutor.
- Do not give unnecessary apologies or repetitive disclaimers.
- Answer the user's actual question directly.
- Explain difficult technical concepts using simple language.

MAIN TECHNICAL SUBJECTS:
Arduino, ESP32, ESP8266, Raspberry Pi, microcontrollers,
microprocessors, sensors, actuators, electronics, circuit design,
PCB design, Arduino IDE, C, C++, Python, PHP, JavaScript,
databases, MQTT, HTTP, Wi-Fi, Bluetooth, Telegram bots,
IoT platforms, embedded Linux and robotics.

DIAGRAMS AND CIRCUITS:
- Provide diagrams whenever they help explain a project.
- Use Mermaid flowcharts for system architecture.
- Use clean, readable ASCII wiring diagrams when necessary.
- Use labeled component diagrams and pin-connection tables.
- Explain signal direction and power connections.
- Clearly identify VCC, GND, signal and communication pins.
- Never invent component pins or electrical specifications.
- If a pinout depends on a particular board version, ask which
  board the user has or explain the assumption.
- For circuits, explain the connections step by step.
- Keep diagrams organized and avoid confusing layouts.
- For website responses, use Mermaid-compatible diagram syntax
  when a diagram is requested.
- For Telegram responses, prefer simple text diagrams and tables.
- Do not claim that a PNG or photograph has been generated
  unless an actual image-generation service has produced it.

CODE:
When providing code:
- Give complete, practical code where possible.
- Identify the board and programming environment.
- Include required libraries and installation instructions.
- Explain where each code section should be pasted.
- Explain important pins and configuration values.
- Include testing instructions and troubleshooting advice.
- Avoid incomplete examples unless the user requests a short example.
- Never claim code was tested on physical hardware unless it was.

PROJECT DEVELOPMENT:
When presenting a complete project, include:
1. Project overview
2. Objectives
3. Required components and tools
4. System block diagram
5. Circuit connections
6. Complete source code
7. Working principle
8. Testing procedure
9. Possible improvements

DEBUGGING:
- Read the exact error message carefully.
- Identify the likely cause.
- Give one practical solution at a time.
- Explain how to verify that the solution worked.
- Do not invent errors or claim a fix was successful without evidence.

EDUCATIONAL SUPPORT:
- Help university and college students learn engineering.
- Suggest realistic final-year projects.
- Explain the purpose of each component.
- Provide practical examples and learning resources when useful.
- Encourage safe experimentation and good engineering practices.

LANGUAGES:
- Support English, French and Kinyarwanda.
- Reply in the language used by the user.
- Keep technical names and code syntax accurate.

SAFETY:
- Warn about dangerous voltage and current.
- Never recommend unsafe mains wiring.
- Explain power requirements and voltage compatibility.
- Do not assume that a microcontroller pin can power a high-current device.
- Recommend appropriate drivers, relays, fuses and protection circuits
  when required.
- Never claim physical hardware testing that did not happen.

RESPONSE STYLE:
- Use clear headings.
- Use readable tables.
- Use numbered steps for instructions.
- Keep explanations organized and useful.
- Avoid unnecessarily long introductions.
- Be a capable engineering assistant, not a generic chatbot.
"""


# ============================================================
# 3. DATABASE AND CHAT HISTORY
# ============================================================

def db():
    con = sqlite3.connect(DB_PATH, timeout=20)
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

        con.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_user_id
            ON messages(user_key, id)
        """)


def save_message(user_key: str, role: str, content: str):
    with db() as con:
        con.execute(
            """
            INSERT INTO messages(user_key, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                user_key,
                role,
                content,
                datetime.now(timezone.utc).isoformat()
            )
        )


def get_history(user_key: str, limit: int = 12):
    with db() as con:
        rows = con.execute(
            """
            SELECT role, content
            FROM messages
            WHERE user_key = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_key, limit)
        ).fetchall()

    return [
        {"role": row["role"], "content": row["content"]}
        for row in reversed(rows)
    ]


def clear_history(user_key: str):
    with db() as con:
        con.execute(
            "DELETE FROM messages WHERE user_key = ?",
            (user_key,)
        )


# ============================================================
# 4. SECURITY
# ============================================================

def check_password(password: Optional[str]):
    required = os.getenv("APP_PASSWORD", "").strip()

    if required and password != required:
        raise HTTPException(
            status_code=401,
            detail="Incorrect application password."
        )


# ============================================================
# 5. GEMINI AI PROVIDER
# ============================================================

async def ask_gemini(history, prompt):

    from google import genai
    from google.genai import types

    key = os.getenv("GEMINI_API_KEY", "").strip()

    if not key:
        raise RuntimeError("GEMINI_API_KEY is not configured.")

    model = os.getenv(
        "GEMINI_MODEL",
        "gemini-3.8-flash"
    ).strip()

    client = genai.Client(api_key=key)

    transcript = []

    for item in history[-10:]:
        label = (
            "User"
            if item["role"] == "user"
            else "CYGAD AI"
        )

        transcript.append(
            f"{label}: {item['content']}"
        )

    transcript.append(f"User: {prompt}")

    response = await asyncio.wait_for(
        asyncio.to_thread(
            client.models.generate_content,
            model=model,
            contents="\n\n".join(transcript),
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.5,
                max_output_tokens=3000
            )
        ),
        timeout=45
    )

    answer = getattr(response, "text", None)

    if not answer:
        raise RuntimeError("Gemini returned an empty response.")

    return answer.strip()


# ============================================================
# 6. GROQ AI PROVIDER
# ============================================================

async def ask_groq(history, prompt):

    from groq import Groq

    key = os.getenv("GROQ_API_KEY", "").strip()

    if not key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    model = os.getenv(
        "GROQ_MODEL",
        "openai/gpt-oss-120b"
    ).strip()

    client = Groq(
        api_key=key,
        timeout=30.0,
        max_retries=1
    )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    messages.extend(history[-10:])

    messages.append({
        "role": "user",
        "content": prompt
    })

    result = await asyncio.wait_for(
        asyncio.to_thread(
            client.chat.completions.create,
            model=model,
            messages=messages,
            temperature=0.5,
            max_tokens=3000
        ),
        timeout=40
    )

    answer = result.choices[0].message.content

    if not answer:
        raise RuntimeError("Groq returned an empty response.")

    return answer.strip()


# ============================================================
# 7. OPTIONAL LOCAL OLLAMA PROVIDER
# ============================================================

async def ask_ollama(history, prompt):

    url = os.getenv(
        "OLLAMA_URL",
        "http://127.0.0.1:11434"
    ).rstrip("/")

    model = os.getenv(
        "OLLAMA_MODEL",
        "qwen2.5:0.5b"
    )

    messages = [
        {
            "role": "system",
            "content": SYSTEM_PROMPT
        }
    ]

    messages.extend(history[-8:])

    messages.append({
        "role": "user",
        "content": prompt
    })

    async with httpx.AsyncClient(timeout=90) as client:

        response = await client.post(
            f"{url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False
            }
        )

        response.raise_for_status()

        data = response.json()

    answer = data.get("message", {}).get("content", "")

    if not answer:
        raise RuntimeError("Ollama returned an empty response.")

    return answer.strip()


# ============================================================
# 8. AUTOMATIC AI PROVIDER SELECTION
# ============================================================

async def generate_reply(
    user_key,
    prompt,
    requested_provider="AUTO"
):

    history = get_history(user_key)

    mode = (requested_provider or "AUTO").upper()

    if mode == "GEMINI":
        order = ["GEMINI"]

    elif mode == "GROQ":
        order = ["GROQ"]

    elif mode == "LOCAL":
        order = ["LOCAL"]

    else:
        # Cloud deployment: use online providers only.
        # Ollama is not automatically attempted because
        # localhost in Inject Cloud is not the user's computer.
        order = ["GEMINI", "GROQ"]

    attempts = []

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
                actual = "Ollama (local)"

            save_message(user_key, "user", prompt)
            save_message(user_key, "assistant", answer)

            logger.info(
                "AI request completed using %s for %s",
                actual,
                user_key
            )

            return answer, actual

        except Exception as exc:

            error = f"{provider}: {type(exc).__name__}: {str(exc)[:250]}"

            attempts.append(error)

            logger.exception(
                "AI provider %s failed for %s",
                provider,
                user_key
            )

    detail = " | ".join(attempts)

    raise RuntimeError(
        "No AI provider could complete the request. "
        + detail
    )


# ============================================================
# 9. API REQUEST MODELS
# ============================================================

class ChatRequest(BaseModel):

    message: str = Field(
        min_length=1,
        max_length=8000
    )

    session_id: str = Field(
        min_length=8,
        max_length=100
    )

    provider: str = Field(
        default="AUTO",
        pattern="^(AUTO|GEMINI|GROQ|LOCAL)$"
    )


class ClearRequest(BaseModel):

    session_id: str = Field(
        min_length=8,
        max_length=100
    )


# ============================================================
# 10. TELEGRAM BOT
# ============================================================

telegram_task = None
telegram_stop = asyncio.Event()


async def telegram_send(client, token, chat_id, message):

    # Telegram messages must be below 4096 characters.
    chunks = [
        message[i:i + 3900]
        for i in range(0, len(message), 3900)
    ] or [" "]

    for chunk in chunks:

        response = await client.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": chunk
            }
        )

        response.raise_for_status()

        result = response.json()

        if not result.get("ok"):
            raise RuntimeError("Telegram could not send the message.")


async def telegram_loop():

    token = os.getenv(
        "TELEGRAM_BOT_TOKEN",
        ""
    ).strip()

    if not token:
        logger.info("Telegram bot is not configured.")
        return

    allowed_raw = os.getenv(
        "TELEGRAM_ALLOWED_USER_IDS",
        ""
    ).strip()

    allowed = {
        item.strip()
        for item in allowed_raw.split(",")
        if item.strip()
    }

    offset = None

    async with httpx.AsyncClient(timeout=40) as client:

        # Remove an existing webhook before using polling.
        try:

            await client.post(
                f"https://api.telegram.org/bot{token}/deleteWebhook",
                json={"drop_pending_updates": False}
            )

        except Exception:

            logger.warning("Could not delete the previous Telegram webhook.")

        logger.info("CYGAD AI Telegram polling started.")

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

                if not data.get("ok"):
                    raise RuntimeError("Telegram getUpdates failed.")

                for update in data.get("result", []):

                    offset = update["update_id"] + 1

                    msg = (
                        update.get("message")
                        or update.get("edited_message")
                    )

                    if not msg or not msg.get("text"):
                        continue

                    chat_id = msg["chat"]["id"]

                    sender_id = str(
                        msg.get("from", {}).get("id", "")
                    )

                    message = msg["text"].strip()

                    if not message:
                        continue

                    # Optional private-user restriction.
                    if allowed and sender_id not in allowed:

                        await telegram_send(
                            client,
                            token,
                            chat_id,
                            "Sorry, this CYGAD AI bot is private."
                        )

                        continue

                    user_key = f"telegram:{chat_id}"

                    # START AND HELP COMMANDS
                    if message.startswith("/start") or message.startswith("/help"):

                        await telegram_send(
                            client,
                            token,
                            chat_id,
                            (
                                "Welcome to CYGAD AI!\n\n"
                                "Your engineering assistant for:\n"
                                "- IoT and embedded systems\n"
                                "- Arduino, ESP32 and ESP8266\n"
                                "- Electronics and circuit design\n"
                                "- Python, C/C++ and programming\n"
                                "- Sensors, actuators and robotics\n\n"
                                "Ask your technical question to begin.\n\n"
                                "Commands:\n"
                                "/start - Start CYGAD AI\n"
                                "/help - Show help\n"
                                "/reset - Clear your chat history"
                            )
                        )

                        continue

                    # RESET COMMAND
                    if message.startswith("/reset"):

                        clear_history(user_key)

                        await telegram_send(
                            client,
                            token,
                            chat_id,
                            "Your CYGAD AI conversation history has been cleared."
                        )

                        continue

                    # NORMAL AI QUESTION
                    try:

                        answer, used = await generate_reply(
                            user_key,
                            message,
                            "AUTO"
                        )

                        await telegram_send(
                            client,
                            token,
                            chat_id,
                            f"{answer}\n\n— Powered by {used}"
                        )

                    except Exception as exc:

                        logger.exception(
                            "Telegram AI request failed."
                        )

                        await telegram_send(
                            client,
                            token,
                            chat_id,
                            (
                                "CYGAD AI could not complete that request.\n\n"
                                "Please try again later.\n\n"
                                f"Technical error: {type(exc).__name__}"
                            )
                        )

            except asyncio.CancelledError:

                raise

            except Exception:

                logger.exception("Telegram polling error.")

                await asyncio.sleep(5)


# ============================================================
# 11. APPLICATION LIFESPAN
# ============================================================

@asynccontextmanager
async def lifespan(app: FastAPI):

    global telegram_task

    init_db()

    if os.getenv("TELEGRAM_BOT_TOKEN", "").strip():

        telegram_stop.clear()

        telegram_task = asyncio.create_task(
            telegram_loop()
        )

    logger.info("CYGAD AI application started.")

    yield

    telegram_stop.set()

    if telegram_task:

        telegram_task.cancel()

        try:
            await telegram_task

        except asyncio.CancelledError:
            pass

    logger.info("CYGAD AI application stopped.")


# ============================================================
# 12. FASTAPI APPLICATION
# ============================================================

app = FastAPI(
    title="CYGAD AI",
    description="IoT and Embedded Systems AI Assistant",
    version="2.0.0",
    lifespan=lifespan
)

app.mount(
    "/static",
    StaticFiles(directory=str(STATIC)),
    name="static"
)


# ============================================================
# 13. WEBSITE ROUTES
# ============================================================

@app.get("/")
async def home():

    return FileResponse(
        STATIC / "index.html"
    )


@app.get("/manifest.json")
async def manifest():

    return FileResponse(
        STATIC / "manifest.json",
        media_type="application/manifest+json"
    )


@app.get("/sw.js")
async def service_worker():

    return FileResponse(
        STATIC / "sw.js",
        media_type="application/javascript"
    )


# ============================================================
# 14. HEALTH CHECK
# ============================================================

@app.get("/health")
async def health():

    return {
        "ok": True,
        "application": "CYGAD AI",
        "version": "2.0.0",
        "gemini_configured": bool(
            os.getenv("GEMINI_API_KEY", "").strip()
        ),
        "groq_configured": bool(
            os.getenv("GROQ_API_KEY", "").strip()
        ),
        "telegram_configured": bool(
            os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        ),
        "local_model": os.getenv(
            "OLLAMA_MODEL",
            "qwen2.5:0.5b"
        )
    }


# ============================================================
# 15. WEBSITE CHAT API
# ============================================================

@app.post("/api/chat")
async def chat(
    request: ChatRequest,
    x_app_password: Optional[str] = Header(default=None)
):

    check_password(x_app_password)

    try:

        answer, provider = await generate_reply(
            f"web:{request.session_id}",
            request.message,
            request.provider
        )

        return {
            "answer": answer,
            "provider": provider
        }

    except Exception as exc:

        logger.exception("Website chat request failed.")

        raise HTTPException(
            status_code=503,
            detail=str(exc)
        )


# ============================================================
# 16. CLEAR WEBSITE CHAT HISTORY
# ============================================================

@app.post("/api/clear")
async def clear(
    request: ClearRequest,
    x_app_password: Optional[str] = Header(default=None)
):

    check_password(x_app_password)

    clear_history(
        f"web:{request.session_id}"
    )

    return {
        "ok": True,
        "message": "Chat history cleared."
    }

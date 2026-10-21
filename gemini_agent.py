"""
Telegram kanalni avtomatik yurituvchi agent - Multi-Model versiya
Agar 1-model ishlamasa 2-chi, 3-chisiga o\'tadi
"""

import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import requests

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
CHANNEL = os.environ.get("TELEGRAM_CHANNEL")

if not GEMINI_API_KEY or not BOT_TOKEN or not CHANNEL:
    print("XATO: GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL secretlari topilmadi!")
    sys.exit(1)

TOPIC = os.environ.get("CHANNEL_TOPIC", "dunyo yangiliklari")
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Tashkent"))
HISTORY_FILE = "posted_history.json"

# Vergul bilan yozilgan modellarni ro\'yxatga aylantiramiz
MODELS_TO_TRY = [m.strip() for m in os.environ.get("MODEL", "gemini-2.0-flash").split(",") if m.strip()]

SYSTEM_PROMPT = f"""Sen Telegram kanal muharririsan. Kanal mavzusi: {TOPIC}.
Vazifang: internetda eng yangi va muhim yangilikni topib, o\'zbek tilida (lotin yozuvi) qisqa post yozish.

Qoidalar:
- Faqat so\'nggi 24-48 soat ichidagi haqiqiy yangilikni tanla. Hech narsa to\'qima.
- Post 400-900 belgi bo\'lsin: jozibador sarlavha, 2-4 gapli mazmun, oxirida manba nomi.
- Telegram HTML formatidan foydalan: <b>qalin</b>, <i>kursiv</i>.
  Boshqa HTML teg ishlatma. "<" va ">" belgilarini oddiy matnda ishlatma.
- Ortiqcha emoji ishlatma (1-3 ta yetarli).
- Quyida allaqachon joylangan mavzular ro\'yxati bor, ularni takrorlama.
- Agar yangi va arziydigan yangilik topolmasang, faqat SKIP so\'zini yoz.
- Javobda faqat tayyor post matni bo\'lsin, izoh yoki kirish so\'zlarsiz."""

def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-60:], f, ensure_ascii=False, indent=1)

def call_gemini(prompt):
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    last_error = None

    for model in MODELS_TO_TRY:
        print(f"Sinab ko\'rilmoqda: {model}")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {"maxOutputTokens": 4000},
        }
        for attempt in range(2):
            r = requests.post(url, headers=headers, json=body, timeout=90)
            if r.ok:
                print(f"Muvaffaqiyatli model: {model}")
                return r.json()
            last_error = f"{model} -> {r.status_code} {r.text[:400]}"
            print(f"Xato: {last_error}")
            if r.status_code in (429, 500, 503):
                time.sleep(5 * (attempt + 1))
                continue
            break
    
    raise RuntimeError(f"Hamma modellar ishlamadi. Oxirgi xato: {last_error}")

def generate_post(history):
    recent = "\n".join(f"- {h[\'summary\']}" for h in history[-20:]) or "(hali yo\'q)"
    prompt = (
        f"Bugun: {datetime.now(TZ):%Y-%m-%d}.\n"
        f"Allaqachon joylangan mavzular:\n{recent}\n\nYangi post yoz."
    )
    data = call_gemini(prompt)
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
    if text and not text.upper().startswith("SKIP") and chunks:
        web = chunks[0].get("web") or {}
        uri, title = web.get("uri"), web.get("title", "Manba")
        if uri:
            text += f\'\n\n<a href="{uri}">{title}</a>\'
    return text

def send_to_channel(text):
    r = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHANNEL, "text": text[:4096], "parse_mode": "HTML"},
        timeout=30,
    )
    if not r.ok:
        raise RuntimeError(f"Telegram xatosi: {r.status_code} {r.text}")

def run_once():
    history = load_history()
    post = generate_post(history)
    if not post or post.upper().startswith("SKIP"):
        print("Yangi yangilik topilmadi, post o\'tkazib yuborildi.")
        return
    send_to_channel(post)
    summary = post.replace("\n", " ")[:120]
    history.append({"time": datetime.now(TZ).isoformat(), "summary": summary})
    save_history(history)
    print("Post joylandi:", summary)

if __name__ == "__main__":
    run_once()

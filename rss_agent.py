"""
Trading kanal agenti (RSS + Gemini).

Qanday ishlaydi:
1. RSS lentalaridan so'nggi 48 soatdagi yangiliklar yig'iladi (bepul).
2. Gemini ularning ichidan treyderlar uchun eng muhimini tanlaydi va
   FAQAT berilgan sarlavha/qisqacha mazmun asosida o'zbekcha post yozadi.
3. Post kanalga joylanadi, oxirida manba havolasi va ogohlantirish qo'shiladi.

Muhit o'zgaruvchilari:
    GEMINI_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL
    TIMEZONE  - ixtiyoriy (Asia/Tashkent)
    MODEL     - ixtiyoriy (gemini-3.8-flash)
    FEEDS     - ixtiyoriy, vergul bilan ajratilgan RSS manzillari
"""

import html
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

import requests

GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL = os.environ["TELEGRAM_CHANNEL"]
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Tashkent"))
MODEL = os.environ.get("MODEL", "gemini-3.8-flash")
HISTORY_FILE = "posted_history.json"

# Diqqat: bu manzillar vaqt o'tishi bilan o'zgarishi mumkin.
# Qaysi biri ishlayotganini Actions logidan ko'rasiz.
DEFAULT_FEEDS = [
    "https://www.fxstreet.com/rss/news",
    "https://www.fxstreet.com/rss/analysis",
    "https://cointelegraph.com/rss",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://www.investing.com/rss/news.rss",
]
FEEDS = [f.strip() for f in os.environ.get("FEEDS", "").split(",") if f.strip()] or DEFAULT_FEEDS

MAX_AGE_HOURS = 48
MAX_PER_FEED = 6
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ChannelAgent/1.0)"}

SYSTEM_PROMPT = """Sen trading (treyding) mavzusidagi Telegram kanal muharririsan.
Senga yangiliklar ro'yxati beriladi. Vazifang: treyderlar uchun eng muhim bittasini tanlab,
o'zbek tilida (lotin yozuvi) qisqa post yozish.

Qat'iy qoidalar:
- Faqat berilgan sarlavha va qisqacha mazmundagi ma'lumotga tayan. Raqam, narx darajasi,
  sana yoki iqtiboslarni o'zingdan to'qima.
- "Sotib ol", "sot", "kafolatli daromad" kabi signal yoki va'da berma.
- Yangilikning bozorga ta'siri haqida umumiy fikr aytishing mumkin, lekin buni
  "ehtimol", "kutilmoqda" kabi so'zlar bilan, taxmin sifatida yoz.
- Post 400-800 belgi: jozibador <b>sarlavha</b>, 2-4 gapli mazmun.
- Faqat <b> va <i> teglarini ishlat. "<" va ">" belgilarini oddiy matnda ishlatma.
- 1-3 ta emoji yetarli.
- Havola va ogohlantirishni YOZMA, ularni dastur o'zi qo'shadi.

Javob formati:
- Birinchi qatorda FAQAT tanlagan yangilikning raqami (masalan: 3).
- Keyin bo'sh qator va tayyor post matni.
- Agar ro'yxatda arziydigan yangilik bo'lmasa, faqat SKIP so'zini yoz."""


def local(tag):
    return tag.rsplit("}", 1)[-1]


def child_text(el, names):
    for c in el:
        if local(c.tag) in names and c.text and c.text.strip():
            return c.text.strip()
    return ""


def child_link(el):
    for c in el:
        if local(c.tag) == "link":
            if c.text and c.text.strip():
                return c.text.strip()
            if c.attrib.get("href"):
                return c.attrib["href"].strip()
    return ""


def clean(text, limit=350):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def parse_date(value):
    if not value:
        return None
    try:
        dt = parsedate_to_datetime(value)
    except Exception:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_feed(url):
    r = requests.get(url, headers=HEADERS, timeout=25)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    source = urlparse(url).netloc.replace("www.", "")
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        title = clean(child_text(el, ("title",)), 200)
        link = child_link(el)
        if not title or not link:
            continue
        items.append(
            {
                "source": source,
                "title": title,
                "link": link,
                "summary": clean(child_text(el, ("description", "summary", "content", "encoded"))),
                "date": parse_date(child_text(el, ("pubDate", "published", "updated", "date"))),
            }
        )
    return items


def collect_candidates(history):
    seen_links = {h.get("link") for h in history if h.get("link")}
    seen_titles = {h.get("summary") for h in history}
    cutoff = datetime.now(timezone.utc) - timedelta(hours=MAX_AGE_HOURS)
    result = []
    worked = 0
    for url in FEEDS:
        try:
            items = fetch_feed(url)
            worked += 1
        except Exception as e:
            print(f"Lenta ishlamadi: {url} -> {e}")
            continue
        fresh = []
        for it in items:
            if it["link"] in seen_links or it["title"] in seen_titles:
                continue
            if it["date"] and it["date"] < cutoff:
                continue
            fresh.append(it)
        fresh.sort(key=lambda x: x["date"] or datetime.now(timezone.utc), reverse=True)
        print(f"Lenta OK: {url} -> {len(fresh)} ta yangi")
        result.extend(fresh[:MAX_PER_FEED])
    if worked == 0:
        raise RuntimeError("Hech bir RSS lentasi ochilmadi. FEEDS manzillarini tekshiring.")
    return result


def call_gemini(prompt):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 4000},
    }
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    last = None
    for attempt in range(3):
        r = requests.post(url, headers=headers, json=body, timeout=90)
        if r.ok:
            return r.json()
        last = r
        if r.status_code in (429, 500, 503):
            time.sleep(10 * (attempt + 1))
            continue
        break
    raise RuntimeError(f"Gemini xatosi: {last.status_code} {last.text[:500]}")


def pick_and_write(candidates):
    lines = []
    for i, c in enumerate(candidates, 1):
        lines.append(f"{i}. [{c['source']}] {c['title']} - {c['summary']}")
    prompt = "Yangiliklar ro'yxati:\n" + "\n".join(lines)
    data = call_gemini(prompt)
    cand = (data.get("candidates") or [{}])[0]
    parts = (cand.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts).strip()
    if not text or text.upper().startswith("SKIP"):
        return None, None
    m = re.match(r"\s*(\d+)", text)
    if not m:
        print("Model formatni buzdi:", text[:200])
        return None, None
    idx = int(m.group(1)) - 1
    if not 0 <= idx < len(candidates):
        print("Model noto'g'ri raqam tanladi:", idx + 1)
        return None, None
    return candidates[idx], text[m.end():].strip()


def telegram_send(text, parse_mode="HTML"):
    payload = {"chat_id": CHANNEL, "text": text[:4096]}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    return requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload, timeout=30
    )


def send_to_channel(post, item):
    footer = (
        '\n\n<a href="' + html.escape(item["link"], quote=True) + '">Manba: '
        + html.escape(item["source"]) + "</a>"
        + "\n⚠️ <i>Bu moliyaviy maslahat emas.</i>"
    )
    r = telegram_send(post + footer)
    if r.status_code == 400 and "parse" in r.text.lower():
        plain = re.sub(r"<[^>]+>", "", post) + "\n\nManba: " + item["link"]
        plain += "\n⚠️ Bu moliyaviy maslahat emas."
        r = telegram_send(plain, parse_mode=None)
    if not r.ok:
        raise RuntimeError(f"Telegram xatosi: {r.status_code} {r.text}")


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []


def save_history(history):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history[-100:], f, ensure_ascii=False, indent=1)


def run_once():
    history = load_history()
    candidates = collect_candidates(history)
    if not candidates:
        print("Yangi yangilik yo'q.")
        return
    item, post = pick_and_write(candidates)
    if not item or not post:
        print("Model post yozmadi (SKIP yoki xato format).")
        return
    send_to_channel(post, item)
    history.append(
        {
            "time": datetime.now(TZ).isoformat(),
            "summary": item["title"],
            "link": item["link"],
        }
    )
    save_history(history)
    print("Post joylandi:", item["title"])


if __name__ == "__main__":
    run_once()

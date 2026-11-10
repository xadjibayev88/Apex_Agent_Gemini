"""Forex maktabi: har kuni bitta dars Telegram kanalga — brendli rasm-kartochka, matn, tugmalar va viktorina.

Darslar: content/lessons.json (birinchi javob varianti to'g'ri; yuborishda aralashtiriladi).
Tugmalar: hamkorlik havolasi (ochiq aytilgan) va kanalga taklif havolasi. Holat: school_state.json.
DRY_RUN=1 bo'lsa hech narsa yuborilmaydi (rasm yasaladi, matn chiqariladi).
"""
from __future__ import annotations

import html
import json
import os
import random
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from PIL import Image, ImageDraw, ImageFont

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHANNEL", "").strip()
AFFILIATE = os.environ.get("AFFILIATE_LINK", "https://affs.click/AeH5W").strip()
INVITE = os.environ.get("CHANNEL_INVITE", "https://t.me/Apex_Trader_Uz").strip()
BRAND = os.environ.get("BRAND_NAME", "ApexTrader_Uz")
TZ = ZoneInfo(os.environ.get("TIMEZONE", "Asia/Tashkent"))
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"
STATE = Path("school_state.json")
RISK = ("Forex va CFD savdosi yuqori xavf bilan bog'liq, mijozlarning katta qismi pul yo'qotadi. "
        "Bu moliyaviy maslahat emas.")
FONTS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVuSans-Bold.ttf"]
NAVY, PANEL, ACCENT, GOLD, WHITE, MUTED = (7, 12, 26), (16, 24, 46), (0, 214, 160), (255, 196, 64), (242, 246, 252), (150, 166, 190)


def font(size: int):
    for p in FONTS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def wrap(d, text: str, f, max_w: int) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        test = (cur + " " + word).strip()
        if d.textlength(test, font=f) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def strip_emoji(s: str) -> str:
    return "".join(ch for ch in s if ord(ch) < 0x2190 or 0x2C00 <= ord(ch) < 0xFE00).strip()


def make_card(lesson: dict, number: int, total: int, path: str) -> None:
    """1080x1080 kartochka: seriya nomi, dars raqami, sarlavha, jarayon chizig'i."""
    W = H = 1080
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    for y in range(0, H, 4):
        k = y / H
        d.rectangle([0, y, W, y + 4], fill=tuple(int(a + (b - a) * k) for a, b in zip(NAVY, (12, 22, 48))))
    for x in range(0, W, 90):
        d.line([x, 0, x, H], fill=(18, 28, 54))
    for y in range(0, H, 90):
        d.line([0, y, W, y], fill=(18, 28, 54))
    d.rounded_rectangle([70, 70, 84, 126], radius=6, fill=ACCENT)
    d.text((104, 72), BRAND, font=font(44), fill=WHITE)
    d.rounded_rectangle([70, 190, 470, 262], radius=36, fill=GOLD)
    d.text((104, 204), "FOREX MAKTABI", font=font(38), fill=NAVY)
    d.text((70, 300), f"Dars {number} / {total}", font=font(54), fill=MUTED)
    title = strip_emoji(lesson["text"].splitlines()[0])
    size = 110
    while size > 56:
        lines = wrap(d, title, font(size), W - 140)
        if len(lines) <= 3:
            break
        size -= 8
    y = 420
    for line in lines[:4]:
        d.text((70, y), line, font=font(size), fill=WHITE)
        y += int(size * 1.18)
    d.rounded_rectangle([70, 900, W - 70, 916], radius=8, fill=PANEL)
    d.rounded_rectangle([70, 900, 70 + int((W - 140) * number / total), 916], radius=8, fill=ACCENT)
    d.text((70, 950), "Har kuni bitta dars + viktorina", font=font(34), fill=MUTED)
    d.text((70, 1004), "Moliyaviy maslahat emas. Savdo yuqori xavfli.", font=font(26), fill=MUTED)
    img.save(path, quality=92)


def caption(lesson: dict, number: int, total: int) -> str:
    text = lesson["text"].replace("{LINK}", AFFILIATE)
    first, _, rest = text.partition("\n")
    return (f"<b>{html.escape(first, quote=False)}</b>\n<i>Forex maktabi · dars {number}/{total}</i>\n"
            f"{html.escape(rest, quote=False)}\n\n<i>⚠️ {html.escape(RISK, quote=False)}</i>")


def keyboard() -> str:
    return json.dumps({"inline_keyboard": [
        [{"text": "📈 Hisob ochish (hamkorlik havolasi)", "url": AFFILIATE}],
        [{"text": "📢 Kanalga qo'shilish", "url": INVITE}]]})


def tg(method: str, files=None, **data) -> dict:
    r = requests.post(f"https://api.telegram.org/bot{TOKEN}/{method}", data=data, files=files, timeout=60)
    body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if not body.get("ok"):
        raise RuntimeError(f"Telegram {method}: {r.status_code} {body.get('description', '')}")
    return body["result"]


def quiz_payload(quiz: dict, seed: int) -> dict:
    """Variantlarni aralashtiradi (to'g'ri javob har doim birinchi turmasin)."""
    options = list(quiz["options"])
    correct = options[0]
    random.Random(seed).shuffle(options)
    return {"question": "🧠 Viktorina: " + quiz["question"], "options": json.dumps(options, ensure_ascii=False),
            "type": "quiz", "correct_option_id": options.index(correct), "explanation": quiz.get("explanation", ""),
            "is_anonymous": "true"}


def main() -> int:
    lessons = json.loads(Path("content/lessons.json").read_text(encoding="utf-8"))
    state = json.loads(STATE.read_text(encoding="utf-8")) if STATE.exists() else {"next": 0, "last_day": ""}
    today = datetime.now(TZ).date().isoformat()
    forced = os.environ.get("LESSON_INDEX", "").strip()
    if state.get("last_day") == today and not forced and not DRY_RUN:
        print("Bugungi dars allaqachon yuborilgan")
        return 0
    idx = (int(forced) if forced else int(state.get("next", 0))) % len(lessons)
    lesson, number, total = lessons[idx], idx + 1, len(lessons)
    card = "/tmp/lesson_card.jpg"
    make_card(lesson, number, total, card)
    cap = caption(lesson, number, total)
    if len(cap) > 1024:
        raise RuntimeError(f"Dars {number} matni juda uzun ({len(cap)} belgi)")
    print(f"Dars {number}/{total}: {lesson['text'].splitlines()[0]} ({len(cap)} belgi), viktorina: {'bor' if lesson.get('quiz') else 'yoq'}")
    if DRY_RUN:
        print(cap)
        print("DRY_RUN: yuborilmadi")
        return 0
    if not (TOKEN and CHAT):
        print("TELEGRAM_BOT_TOKEN yoki TELEGRAM_CHANNEL yo'q")
        return 1
    with open(card, "rb") as fh:
        tg("sendPhoto", files={"photo": fh}, chat_id=CHAT, caption=cap, parse_mode="HTML", reply_markup=keyboard())
    print("Dars yuborildi")
    state.update(next=(idx + 1) % total, last_day=today)
    STATE.write_text(json.dumps(state), encoding="utf-8")
    if lesson.get("quiz"):
        try:  # viktorina yuborilmasa ham dars chiqqan hisoblanadi
            tg("sendPoll", chat_id=CHAT, **quiz_payload(lesson["quiz"], idx))
            print("Viktorina yuborildi")
        except RuntimeError as e:
            print("Viktorina yuborilmadi:", e)
    return 0


if __name__ == "__main__":
    sys.exit(main())

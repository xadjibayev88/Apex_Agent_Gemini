"""Telegram kanalidagi signallardan Instagram Reels yasab joylaydi + kuniga bir marta kanalga chorlov Reels.

Manba: ochiq kanalning veb-ko'rinishi (t.me/s/<kanal>) — login va maxfiy kalit kerak emas.
Cheklovlar: kuniga MAX_SIGNAL_REELS ta signal, orasi kamida GAP_MINUTES; faqat oxirgi MAX_AGE_HOURS soatdagi signallar.
DRY_RUN=1 bo'lsa video yasaladi, lekin Instagramga joylanmaydi (sinov).
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

import requests

CHANNEL = os.environ.get("SIGNAL_CHANNEL", "Apex_Trader_Uz").lstrip("@")
STATE_FILE = "signal_reels_state.json"
MAX_SIGNAL_REELS = int(os.environ.get("MAX_SIGNAL_REELS", "3"))
GAP_MINUTES = int(os.environ.get("SIGNAL_GAP_MINUTES", "60"))
MAX_AGE_HOURS = float(os.environ.get("SIGNAL_MAX_AGE_HOURS", "6"))
PROMO_HOUR = int(os.environ.get("PROMO_HOUR", "19"))  # Toshkent vaqti: shu soatdan keyingi birinchi ishga tushishda chorlov
DRY_RUN = os.environ.get("DRY_RUN", "") == "1"
NUM = r"(\d+(?:[.,]\d+)?)"
HASHTAGS = "#treyding #kripto #signal #bitcoin #forex #apextrader"
DISCLAIMER = "Bu moliyaviy maslahat emas. Savdo yuqori xavf bilan bog'liq, mablag'ni yo'qotish mumkin."


# ---------------------------------------------------------------- signalni o'qish
def parse_signal(text: str) -> dict | None:
    """Apex formati: $TICKER -> LONG/SHORT, Точка входа, Таргеты, Стоп. Mantiqan xato bo'lsa None."""
    head = re.search(r"\$([A-Z0-9]{2,15})\s*(?:->|→|—|-|:)?\s*(LONG|SHORT)\b", text or "", re.I)
    entry = re.search(r"Точка\s+входа\s*:\s*" + NUM, text or "", re.I)
    targets = re.search(r"Таргеты?\s*:\s*([\d.,\s]+)", text or "", re.I)
    stop = re.search(r"Стоп\s*:\s*" + NUM, text or "", re.I)
    if not (head and entry and targets and stop):
        return None
    f = lambda s: float(s.strip(" ,").replace(",", "."))  # noqa: E731
    try:
        tgs = [f(p) for p in re.split(r"[;\s]+|,(?=\s)", targets.group(1).strip()) if p.strip(" ,")]
        e, st = f(entry.group(1)), f(stop.group(1))
    except ValueError:
        return None
    side = head.group(2).upper()
    ok = tgs and e > 0 and st > 0 and (
        (side == "LONG" and st < e and all(t > e for t in tgs)) or (side == "SHORT" and st > e and all(t < e for t in tgs)))
    if not ok:
        return None
    return {"symbol": head.group(1).upper() + "USDT", "side": side, "entry": e, "stop": st,
            "targets": sorted(tgs, reverse=(side == "SHORT"))}


def parse_channel_html(page: str) -> list[dict]:
    """t.me/s sahifasidan xabarlar: [{id, text, time}]."""
    out = []
    for block in page.split('data-post="')[1:]:
        m = re.match(r"[^\"/]+/(\d+)\"", block)
        body = re.search(r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S)
        when = re.search(r'<time datetime="([^"]+)"', block)
        if not (m and body and when):
            continue
        text = re.sub(r"<br\s*/?>", "\n", body.group(1))
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
        try:
            ts = datetime.fromisoformat(when.group(1))
        except ValueError:
            continue
        out.append({"id": int(m.group(1)), "text": text, "time": ts})
    return out


def fetch_messages() -> list[dict]:
    r = requests.get(f"https://t.me/s/{CHANNEL}", timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return parse_channel_html(r.text)


# ---------------------------------------------------------------- holat
def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {"seen": [], "posts": [], "promo_day": ""}


def save_state(state: dict) -> None:
    state["seen"] = state["seen"][-500:]
    state["posts"] = state["posts"][-100:]
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)


def pick_signal(messages: list[dict], state: dict, now: datetime) -> tuple[dict, dict] | None:
    """Joylanadigan eng yangi signal (limitlar ichida). Ko'rilgan xabarlar state['seen'] ga qo'shiladi."""
    today = [p for p in state["posts"] if p["time"][:10] == now.date().isoformat() and p["kind"] == "signal"]
    recent = [p for p in state["posts"] if p["kind"] == "signal" and datetime.fromisoformat(p["time"]) > now - timedelta(minutes=GAP_MINUTES)]
    fresh = [m for m in messages if m["id"] not in state["seen"]]
    chosen = None
    for m in sorted(fresh, key=lambda x: -x["id"]):
        sig = parse_signal(m["text"])
        too_old = m["time"] < now - timedelta(hours=MAX_AGE_HOURS)
        if sig and not too_old and chosen is None and len(today) < MAX_SIGNAL_REELS and not recent:
            chosen = (m, sig)
        elif sig and not too_old and chosen is None:
            continue  # limit sabab hozir joylanmaydi: keyingi safar uchun "ko'rilmagan" qoladi
        if not sig or too_old or (chosen and chosen[0] is m):
            state["seen"].append(m["id"])
    return chosen


def caption_for(sig: dict) -> str:
    fmt = lambda p: f"{p:.8f}".rstrip("0").rstrip(".")  # noqa: E731
    rr = abs(sig["targets"][-1] - sig["entry"]) / abs(sig["entry"] - sig["stop"])
    return (f"${sig['symbol'].replace('USDT', '')} {sig['side']} signali\n\n"
            f"Kirish: {fmt(sig['entry'])}\nTargetlar: {', '.join(fmt(t) for t in sig['targets'])}\nStop: {fmt(sig['stop'])}\n"
            f"Risk/Reward: 1:{rr:.2f}\n\n"
            f"Signallar birinchi bo'lib Telegram kanalimizda chiqadi: t.me/{CHANNEL} (havola profilda)\n\n"
            f"{DISCLAIMER}\n\n{HASHTAGS}")


PROMO_CAPTION = (f"Kunlik savdo signallari, kripto va oltin tahlili, bozor yangiliklari — o'zbek tilida.\n\n"
                 f"Telegram kanal: t.me/{CHANNEL} (havola profilda)\n\n{DISCLAIMER}\n\n{HASHTAGS}")


# ---------------------------------------------------------------- asosiy
def main() -> int:
    import rss_ig_agent as base  # Instagram, repo va shrift yordamchilari (mavjud avtomatdan)
    import signal_fx

    now = datetime.now(base.TZ)
    state = load_state()
    try:
        messages = fetch_messages()
    except requests.RequestException as e:
        print("Kanal sahifasi ochilmadi:", type(e).__name__)
        return 1
    print(f"Kanaldan {len(messages)} ta xabar o'qildi")
    stamp = now.strftime("%Y%m%d_%H%M%S")
    path = f"images/reel_sig_{stamp}.mp4"
    choice = pick_signal(messages, state, now)
    if choice:
        m, sig = choice
        kind, caption = "signal", caption_for(sig)
        print(f"Signal: {sig['symbol']} {sig['side']} (xabar {m['id']})")
        signal_fx.make_signal_reel(sig, base.BRAND, CHANNEL, path, base.ffmpeg_exe(), base.FONT_PATHS, base.find_music(),
                                   m["time"].astimezone(base.TZ).strftime("%H:%M"))
    elif state.get("promo_day") != now.date().isoformat() and now.hour >= PROMO_HOUR:
        kind, caption = "promo", PROMO_CAPTION
        print("Bugungi chorlov Reels")
        signal_fx.make_promo_reel(base.BRAND, CHANNEL, path, base.ffmpeg_exe(), base.FONT_PATHS, base.find_music(), seed=now.toordinal())
        state["promo_day"] = now.date().isoformat()
    else:
        print("Yangi signal yo'q (yoki limit), chorlov ham bugun chiqqan/vaqti kelmagan")
        save_state(state)
        return 0
    print("Video tayyor:", os.path.getsize(path) // 1024, "KB")
    if DRY_RUN:
        print("DRY_RUN: Instagramga joylanmadi")
        return 0  # holat saqlanmaydi: sinov navbatni sarflamaydi
    url = base.publish_to_repo(path, "images/reel_*.mp4", 6)
    base.ig_publish_reel_url(url, caption)
    print("Instagram Reels joylandi:", kind)
    state["posts"].append({"time": now.isoformat(timespec="seconds"), "kind": kind})
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())

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
    text = text or ""
    # sarlavha: "$MASK -> LONG" yoki "📈 JTO LONG плечо x25" (leverage ataylab o'qilmaydi)
    head = re.search(r"^\W*\$?([A-Z0-9]{2,15})\s*(?:->|→|—|-|:)?\s*(LONG|SHORT)\b", text, re.I | re.M)
    entry = re.search(r"Точка\s+входа\s*:[^\d\n]*" + NUM, text, re.I)   # "0.3743" yoki "рынок (0.3388)"
    numbered = re.findall(r"Таргет\s*\d+\s*:\s*" + NUM, text, re.I)      # "Таргет 1: 0.3423" qatorlari
    targets = re.search(r"Таргеты?\s*:\s*([\d.,\s]+)", text, re.I)
    stop = re.search(r"Стоп\s*:\s*" + NUM, text, re.I)
    if numbered:
        targets = re.match(r"(.*)", ", ".join(numbered))
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
            if m and DRY_RUN:  # tashxis: xabar nega o'qilmadi
                classes = sorted(set(re.findall(r'class="(tgme_widget_message_[a-z_]+)', block)))
                print(f"  [o'qilmadi] xabar {m.group(1)}: matn={'bor' if body else 'yoq'}, vaqt={'bor' if when else 'yoq'}, bloklar={classes[:14]}")
            continue
        text = re.sub(r"<br\s*/?>", "\n", body.group(1))
        text = html.unescape(re.sub(r"<[^>]+>", "", text))
        try:
            ts = datetime.fromisoformat(when.group(1))
        except ValueError:
            continue
        reply = re.search(r'<a class="tgme_widget_message_reply[^"]*"[^>]*href="[^"]*/(\d+)"', block)
        if DRY_RUN and not reply and "reply" in block:  # tashxis: javob belgisi bor, lekin o'qilmadi
            i = block.find("reply")
            print(f"  [javob o'qilmadi] xabar {m.group(1)}: ...{block[max(0, i - 60):i + 160]!r}")
        out.append({"id": int(m.group(1)), "text": text, "time": ts, "reply_to": int(reply.group(1)) if reply else None})
    return out


# Natija faqat aniq ibora bo'lsa tan olinadi ("тейк 1 взят", "таргет достигнут", "+35%", "закрыл в плюс");
# umumiy gaplar ("идем к цели", "хорошей прибыли") natija emas.
PROFIT_RE = re.compile(
    r"(?:тейк|таргет|цель|\btp)\s*№?\s*\d?\s*\S{0,12}\s*(?:взят|достигнут|выполнен|закрыт|✅)"
    r"|(?:взят|достигнут|выполнен)\w*\s+(?:\S{1,12}\s+)?(?:тейк|таргет|цель)"
    r"|\+\s*\d+(?:[.,]\d+)?\s*[%$]"                                                   # "+26%" yoki "+91.84$"
    r"|(?:забра\w+|взя\w+|сня\w+|зафиксир\w+)[^.\n]{0,25}(?:тейк|таргет|цел[ьи]|профит|прибыл)"  # "забрали первый тейк"
    r"|(?:\d\s*-?(?:я|ая|й|ый|ой)?|перв\w+|втор\w+|трет\w+)\s*(?:цель|тейк|таргет)\s+(?:тут|есть|взят\w*|достигнут\w*)"  # "1я цель тут"
    r"|(?:закры\w+|зафиксир\w+)[^.\n]{0,40}(?:плюс|профит|прибыл)|профит\w*\s+зафиксир", re.I)
# Zarar ham faqat aniq ibora bo'lsa: "выбило по стопу", "стоп сработал", "закрыл в минус", "убыток".
# "Ставим стоп" yoki signal ichidagi "Стоп: 0.32" zarar emas.
LOSS_RE = re.compile(
    r"по\s+стопу|(?:выбил\w*|сработал\w*|словил\w*|задел\w*)[^.\n]{0,25}стоп|стоп(?:[- ]?лосс)?\w*\s+(?:сработал|выбил|задет)"
    r"|(?:закры\w+|зафиксир\w+)[^.\n]{0,40}(?:минус|(?<!без)убыт)|(?<!без)убыт(?:ок|ка|ку|ком)\b|ликвидир|-\s*\d+(?:[.,]\d+)?\s*%\s*❌", re.I)
TARGET_NO_RE = re.compile(r"(?:тейк|таргет|цель|tp)\s*№?\s*(\d)|(\d)\s*-?(?:я|ая|й|и|ый|ой)?\s*(?:тейк|таргет|цель)", re.I)
ORDINALS = {"перв": 1, "втор": 2, "трет": 3, "четв": 4}


def parse_result(text: str) -> dict | None:
    """Savdo yopilgani haqidagi xabar: {"outcome": "profit"|"loss", "target": raqam|None, "pct": "+35%"|None}.

    Foyda ham, stop bilan yopilgan zarar ham natija hisoblanadi (ikkalasi ham videoga chiqadi).
    Yangi signal, umumiy gap yoki bir vaqtda foyda va zarar aytilgan noaniq xabar — None.
    """
    if not text or parse_signal(text):
        return None
    profit, loss = bool(PROFIT_RE.search(text)), bool(LOSS_RE.search(text))
    if profit == loss:  # hech biri yo'q yoki ikkalasi bor (noaniq)
        return None
    if loss:
        return {"outcome": "loss", "target": None, "pct": None}
    target = None
    m = TARGET_NO_RE.search(text)
    if m:
        target = int(m.group(1) or m.group(2))
    else:
        for stem, n in ORDINALS.items():
            if re.search(stem + r"\w*\s+(?:тейк|таргет|цель)", text, re.I):
                target = n
    pct = re.search(r"\+\s*(\d+(?:[.,]\d+)?)\s*%", text)
    return {"outcome": "profit", "target": target, "pct": f"+{pct.group(1)}%" if pct else None}


def result_mark(res: dict) -> int:
    """Takrorlanmaslik belgisi: stop = -1, target N = N, targetsiz foyda = 0."""
    return -1 if res["outcome"] == "loss" else (res["target"] or 0)


def find_result(messages: list[dict], state: dict) -> tuple[dict, str, dict] | None:
    """Kuzatilayotgan signalga tegishli yangi natija xabari: (xabar, signal kaliti, natija).

    Bog'lash: xabar signalga javob (reply) bo'lsa — aniq; bo'lmasa matnda signal tickeri bo'lishi kerak.
    Bir signalning bir targeti uchun faqat bitta natija videosi.
    """
    signals = state.get("signals", {})
    for m in sorted((m for m in messages if m["id"] not in state["seen"]), key=lambda x: x["id"]):
        res = parse_result(m["text"])
        if not res:
            continue
        key = str(m["reply_to"]) if m.get("reply_to") and str(m["reply_to"]) in signals else None
        if key is None:
            for k in sorted(signals, key=int, reverse=True):
                ticker = signals[k]["sig"]["symbol"].replace("USDT", "")
                if re.search(r"(?<![A-Z0-9])\$?" + re.escape(ticker) + r"(?![A-Z0-9])", m["text"], re.I):
                    key = k
                    break
        if key is None:
            continue
        done = signals[key].setdefault("results", [])
        mark = result_mark(res)
        if mark in done or -1 in done or (mark == 0 and done):  # stopdan keyin shu signal yopilgan
            state["seen"].append(m["id"])  # shu natija allaqachon chiqqan
            continue
        return m, key, res
    return None


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
        return {"seen": [], "posts": [], "promo_day": "", "signals": {}}


def save_state(state: dict) -> None:
    state["seen"] = state["seen"][-500:]
    state["posts"] = state["posts"][-100:]
    sigs = state.setdefault("signals", {})
    for k in sorted(sigs, key=int)[:-30]:  # faqat oxirgi 30 ta signal kuzatiladi
        del sigs[k]
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=1)


def pick_signal(messages: list[dict], state: dict, now: datetime, hold: frozenset = frozenset()) -> tuple[dict, dict] | None:
    """Joylanadigan eng yangi signal (limitlar ichida). Ko'rilgan xabarlar state['seen'] ga qo'shiladi."""
    today = [p for p in state["posts"] if p["time"][:10] == now.date().isoformat() and p["kind"] == "signal"]
    recent = [p for p in state["posts"] if p["kind"] == "signal" and datetime.fromisoformat(p["time"]) > now - timedelta(minutes=GAP_MINUTES)]
    fresh = [m for m in messages if m["id"] not in state["seen"]]
    chosen = None
    for m in sorted(fresh, key=lambda x: -x["id"]):
        sig = parse_signal(m["text"])
        if sig and any((v["sig"]["symbol"], v["sig"]["side"], v["sig"]["entry"]) == (sig["symbol"], sig["side"], sig["entry"])
                       for v in state.get("signals", {}).values()):
            sig = None  # shu signal allaqachon joylangan (kanalda ikki marta chiqqan nusxa)
        too_old = m["time"] < now - timedelta(hours=MAX_AGE_HOURS)
        if sig and not too_old and chosen is None and len(today) < MAX_SIGNAL_REELS and not recent:
            chosen = (m, sig)
        elif sig and not too_old and chosen is None:
            continue  # limit sabab hozir joylanmaydi: keyingi safar uchun "ko'rilmagan" qoladi
        if m["id"] in hold:
            continue  # natija xabari: keyingi ishga tushishda natija videosi bo'ladi
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


def result_caption(sig: dict, res: dict) -> str:
    fmt = lambda p: f"{p:.8f}".rstrip("0").rstrip(".")  # noqa: E731
    name = sig["symbol"].replace("USDT", "")
    if res.get("outcome") == "loss":
        move = abs(sig["stop"] - sig["entry"]) / sig["entry"] * 100
        return (f"${name} {sig['side']} signali natijasi\n\n"
                f"Stop-loss ishladi: {fmt(sig['entry'])} → {fmt(sig['stop'])} (narx o'zgarishi -{move:.1f}%, leveragesiz)\n\n"
                f"Zarar bilan yopilgan savdolar ham bo'ladi, shuning uchun har bir savdoda stop-loss va kichik hajm muhim.\n"
                f"Biz foydali va zararli natijalarni birdek ko'rsatamiz: t.me/{CHANNEL} (havola profilda)\n\n{DISCLAIMER}\n\n{HASHTAGS}")
    if res.get("target") and res["target"] <= len(sig["targets"]):
        tp = sig["targets"][res["target"] - 1]
        move = abs(tp - sig["entry"]) / sig["entry"] * 100
        line = f"Target {res['target']} bajarildi: {fmt(sig['entry'])} → {fmt(tp)} (narx o'zgarishi +{move:.1f}%, leveragesiz)"
    else:
        line = "Savdo foyda bilan yopildi" + (f" (kanal xabarida: {res['pct']})" if res.get("pct") else "")
    return (f"${name} {sig['side']} signali natijasi\n\n{line}\n\n"
            f"Har bir signal ham foyda bermaydi: zarar bilan yopilgan savdolar ham bo'ladi.\n"
            f"Signallar va natijalar: t.me/{CHANNEL} (havola profilda)\n\n{DISCLAIMER}\n\n{HASHTAGS}")


def publish_reel(base, url: str, caption: str) -> str | None:
    """Reels joylaydi va media ID ni qaytaradi (asl signalga izoh yozish uchun)."""
    uid = base.ig_user_id()
    cid = base.ig_call("POST", f"{uid}/media", data={"media_type": "REELS", "video_url": url, "thumb_offset": "6000",
                                                    "caption": caption, "share_to_feed": "true"})["id"]
    base.ig_wait(cid, tries=30, delay=5)
    return base.ig_call("POST", f"{uid}/media_publish", data={"creation_id": cid}).get("id")


def comment_on(base, media_id: str | None, text: str) -> None:
    """Asl signal Reels'i ostiga natija haqida izoh (ruxsat bo'lmasa jim o'tadi)."""
    if not media_id:
        return
    try:
        base.ig_call("POST", f"{media_id}/comments", data={"message": text})
        print("Asl signal videosiga izoh yozildi")
    except Exception as e:  # noqa: BLE001 — izoh yozilmasa ham natija videosi chiqqan
        print("Izoh yozilmadi:", str(e)[:120])


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
    for m in (messages if DRY_RUN else messages[-8:]):  # tashxis: oxirgi xabarlar signal deb tanildimi (kanal ochiq, birinchi satr ko'rsatiladi)
        age = (now - m["time"]).total_seconds() / 3600
        first = m["text"].strip().splitlines()[0][:40] if m["text"].strip() else "(matn yo'q)"
        print(f"  xabar {m['id']}: {age:.1f} soat oldin, signal={'ha' if parse_signal(m['text']) else 'yoq'}, natija={'ha' if parse_result(m['text']) else 'yoq'}, javob={m.get('reply_to')} | {first}")
        if DRY_RUN and not parse_signal(m["text"]) and (m.get("reply_to") or re.search(r"long|short|лонг|шорт|тейк|таргет|профит|%", m["text"], re.I)):
            print("    --- to'liq matn (format tashxisi) ---")
            for line in m["text"].splitlines():
                print("    | " + line[:120])
    stamp = now.strftime("%Y%m%d_%H%M%S")
    path = f"images/reel_sig_{stamp}.mp4"
    state.setdefault("signals", {})
    result = find_result(messages, state)
    hold = frozenset({result[0]["id"]}) if result else frozenset()
    choice = pick_signal(messages, state, now, hold)
    after = None  # joylangandan keyin holatga yoziladigan o'zgarish
    if choice:
        m, sig = choice
        kind, caption = "signal", caption_for(sig)
        when = m["time"].astimezone(base.TZ).strftime("%H:%M")
        print(f"Signal: {sig['symbol']} {sig['side']} (xabar {m['id']})")
        signal_fx.make_signal_reel(sig, base.BRAND, CHANNEL, path, base.ffmpeg_exe(), base.FONT_PATHS, base.find_music(), when)
        after = lambda media_id: state["signals"].update({str(m["id"]): {"sig": sig, "media_id": media_id, "when": when, "results": []}})  # noqa: E731
    elif result:
        m, key, res = result
        entry = state["signals"][key]
        sig = entry["sig"]
        kind, caption = "result", result_caption(sig, res)
        print(f"Natija: {sig['symbol']} {res['outcome']} (signal xabari {key}, natija xabari {m['id']}, target={res['target']}, foiz={res['pct']})")
        signal_fx.make_signal_reel(sig, base.BRAND, CHANNEL, path, base.ffmpeg_exe(), base.FONT_PATHS, base.find_music(),
                                   entry.get("when", ""), result=res)

        def after(_media_id, m=m, entry=entry, res=res, caption=caption):
            entry.setdefault("results", []).append(result_mark(res))
            state["seen"].append(m["id"])
            comment_on(base, entry.get("media_id"), caption.split("\n\n")[1] + " Natija videosi profilda.")
    elif state.get("promo_day") != now.date().isoformat() and now.hour >= PROMO_HOUR:
        kind, caption = "promo", PROMO_CAPTION
        print("Bugungi chorlov Reels")
        signal_fx.make_promo_reel(base.BRAND, CHANNEL, path, base.ffmpeg_exe(), base.FONT_PATHS, base.find_music(), seed=now.toordinal())
        state["promo_day"] = now.date().isoformat()
    else:
        print("Yangi signal/natija yo'q (yoki limit), chorlov ham bugun chiqqan/vaqti kelmagan")
        save_state(state)
        return 0
    print("Video tayyor:", os.path.getsize(path) // 1024, "KB")
    if DRY_RUN:
        print("DRY_RUN: Instagramga joylanmadi")
        return 0  # holat saqlanmaydi: sinov navbatni sarflamaydi
    url = base.publish_to_repo(path, "images/reel_*.mp4", 6)
    media_id = publish_reel(base, url, caption)
    print("Instagram Reels joylandi:", kind)
    if after:
        after(media_id)
    state["posts"].append({"time": now.isoformat(timespec="seconds"), "kind": kind})
    save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())

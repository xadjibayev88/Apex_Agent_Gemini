"""
Trading kanal agenti (RSS + Gemini) + Instagram.

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
    IG_ACCESS_TOKEN - Instagram tokeni (bo'lmasa, Instagram o'tkazib yuboriladi)
    IG_USER_ID      - ixtiyoriy (bo'lmasa, token orqali avtomatik topiladi)
    BRAND_NAME      - kartochkadagi nom (standart: ApexTrader_Uz)
    IG_FORMAT       - reel (standart) | image | both
    MIN_GAP_MINUTES - postlar orasidagi eng kam vaqt (standart: 55)
    IG_GAP_HOURS    - Instagram postlari orasidagi eng kam vaqt, soat (standart: 3)
"""

import glob
import html
import json
import os
import re
import subprocess
import sys
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
FALLBACK_MODELS = ["gemini-3.7-flash", "gemini-3.5-flash"]
HISTORY_FILE = "posted_history.json"
IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN", "").strip()
IG_USER_ID = os.environ.get("IG_USER_ID", "").strip()
IG_VERSION = os.environ.get("IG_API_VERSION", "v26.0")
BRAND = os.environ.get("BRAND_NAME", "ApexTrader_Uz")
REPO = os.environ.get("GITHUB_REPOSITORY", "")
BRANCH = os.environ.get("GITHUB_REF_NAME", "main")

# Diqqat: bu manzillar vaqt o'tishi bilan o'zgarishi mumkin.
# Qaysi biri ishlayotganini Actions logidan ko'rasiz.
DEFAULT_FEEDS = [
    "https://cointelegraph.com/rss",
    "https://feeds.marketwatch.com/marketwatch/topstories/",
    "https://www.cnbc.com/id/10000664/device/rss/rss.html",
    "https://www.investing.com/rss/news.rss",
    "https://finance.yahoo.com/news/rssindex",
    "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "http://feeds.bbci.co.uk/news/business/rss.xml",
]
FEEDS = [f.strip() for f in os.environ.get("FEEDS", "").split(",") if f.strip()] or DEFAULT_FEEDS

MAX_AGE_HOURS = 48
MAX_PER_FEED = 8
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
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 4000},
    }
    headers = {"x-goog-api-key": GEMINI_API_KEY, "Content-Type": "application/json"}
    models = []
    for m in [MODEL] + FALLBACK_MODELS:
        if m and m not in models:
            models.append(m)
    last_error = "noma'lum xato"
    for model in models:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(3):
            try:
                r = requests.post(url, headers=headers, json=body, timeout=75)
            except requests.RequestException as e:
                last_error = f"{type(e).__name__}"
                print(f"Gemini ({model}) ulanish xatosi: {last_error}, urinish {attempt + 1}/3")
                time.sleep(5)
                continue
            if r.ok:
                if model != MODEL:
                    print("Zaxira model ishlatildi:", model)
                return r.json()
            last_error = f"{r.status_code} {r.text[:300]}"
            print(f"Gemini ({model}) xato {r.status_code}, urinish {attempt + 1}/3")
            if r.status_code in (429, 500, 503):
                time.sleep(10 * (attempt + 1))
                continue
            break
        # shu model ishlamadi, keyingisiga o'tamiz
    raise RuntimeError("Gemini xatosi: " + last_error)


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



# ---------------- Instagram ----------------

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def strip_tags(text):
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def headline(post):
    m = re.search(r"<b>(.*?)</b>", post, re.S)
    title = strip_tags(m.group(1)) if m else strip_tags(post).split("\n")[0]
    return title[:150]


def load_font(size):
    from PIL import ImageFont

    for p in FONT_PATHS:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    print("Ogohlantirish: shrift topilmadi, standart shrift ishlatiladi.")
    return ImageFont.load_default()


def wrap_text(draw, text, font, max_width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= max_width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def make_card(title, path):
    from PIL import Image, ImageDraw

    size = 1080
    img = Image.new("RGB", (size, size), (12, 18, 32))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, size, 16], fill=(0, 200, 150))
    d.rectangle([80, 120, 92, 330], fill=(0, 200, 150))

    tag_font = load_font(34)
    d.text((120, 120), "TRADING YANGILIKLARI", font=tag_font, fill=(0, 200, 150))

    chosen = None
    for fs in (80, 72, 64, 56, 50, 44):
        font = load_font(fs)
        lines = wrap_text(d, title, font, size - 200)
        if len(lines) <= 9:
            chosen = (font, lines, fs)
            break
    if chosen is None:
        font = load_font(44)
        lines = wrap_text(d, title, font, size - 200)[:9]
        chosen = (font, lines, 44)
    font, lines, fs = chosen

    y = 220
    for ln in lines:
        d.text((100, y), ln, font=font, fill=(240, 244, 250))
        y += int(fs * 1.28)

    brand_font = load_font(40)
    d.text((100, size - 110), "@" + BRAND, font=brand_font, fill=(0, 200, 150))
    img.save(path, "JPEG", quality=92)


def git(*args):
    subprocess.run(["git", *args], check=True)


ACCENT = (0, 200, 150)


def make_reel_frame(title, path):
    """Reels uchun tik (9:16) kadr yasaydi."""
    from PIL import Image, ImageDraw

    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (12, 18, 32))
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, w, 16], fill=ACCENT)
    d.rectangle([80, 520, 92, 700], fill=ACCENT)
    d.text((120, 520), "TRADING YANGILIKLARI", font=load_font(36), fill=ACCENT)

    chosen = None
    for fs in (84, 76, 68, 60, 52, 46):
        font = load_font(fs)
        lines = wrap_text(d, title, font, w - 200)
        if len(lines) <= 11:
            chosen = (font, lines, fs)
            break
    if chosen is None:
        font = load_font(46)
        chosen = (font, wrap_text(d, title, font, w - 200)[:11], 46)
    font, lines, fs = chosen

    y = 640
    for ln in lines:
        d.text((100, y), ln, font=font, fill=(240, 244, 250))
        y += int(fs * 1.3)

    d.text((100, h - 430), "@" + BRAND, font=load_font(42), fill=ACCENT)
    img.save(path, "JPEG", quality=92)


def ffmpeg_exe():
    import shutil

    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


AUDIO_EXT = (".mp3", ".m4a", ".wav", ".aac", ".ogg")


def find_music():
    """Repodagi 'music' papkasi yoki asosiy papkadagi audio fayllardan tasodifiy birini tanlaydi."""
    import random

    files = []
    for pattern in ("music/*", "*"):
        for f in glob.glob(pattern):
            if os.path.isfile(f) and f.lower().endswith(AUDIO_EXT):
                files.append(f)
    return random.choice(files) if files else None


def make_video(frame_path, video_path, music=None):
    """Kadrdan 10 soniyalik, sekin yaqinlashadigan video. Musiqa bo'lsa, qo'shiladi."""
    vf = (
        "scale=1620:2880,"
        "zoompan=z='min(zoom+0.0005,1.10)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        ":d=250:s=1080x1920:fps=25,format=yuv420p"
    )
    cmd = [ffmpeg_exe(), "-y", "-loglevel", "error", "-i", frame_path]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-vf", vf]
    if music:
        cmd += ["-af", "afade=t=in:st=0:d=0.5,afade=t=out:st=9:d=1"]
    cmd += [
        "-t", "10",
        "-c:v", "libx264", "-preset", "veryfast",
        "-c:a", "aac", "-b:a", "128k", "-shortest",
        "-movflags", "+faststart",
        video_path,
    ]
    subprocess.run(cmd, check=True)


def publish_to_repo(path, pattern, keep):
    """Faylni repoga yuklaydi va ochiq havolani qaytaradi."""
    for old in sorted(glob.glob(pattern))[:-keep]:
        os.remove(old)
    git("config", "user.name", "agent-bot")
    git("config", "user.email", "agent-bot@users.noreply.github.com")
    git("add", "-A", "images")
    git("commit", "-m", "media")
    git("push")
    url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/{path}"
    for _ in range(12):
        try:
            resp = requests.head(url, timeout=15)
            if resp.status_code == 200:
                print("Havola ochiq:", url, "| Content-Type:", resp.headers.get("Content-Type"))
                return url
        except requests.RequestException:
            pass
        time.sleep(5)
    raise RuntimeError(
        "Fayl ochiq havolada ko'rinmadi. Repo 'Public' ekanini tekshiring: " + url
    )


def ig_call(method, path, **kwargs):
    url = f"https://graph.instagram.com/{IG_VERSION}/{path}"
    if method == "GET":
        params = {"access_token": IG_TOKEN}
        params.update(kwargs.get("params", {}))
        r = requests.get(url, params=params, timeout=40)
    else:
        data = {"access_token": IG_TOKEN}
        data.update(kwargs.get("data", {}))
        r = requests.post(url, data=data, timeout=60)
    if not r.ok:
        raise RuntimeError(f"Instagram xatosi: {r.status_code} {r.text[:400]}")
    return r.json()


def ig_user_id():
    if IG_USER_ID:
        return IG_USER_ID
    me = ig_call("GET", "me", params={"fields": "user_id,username"})
    return me.get("user_id") or me.get("id")


def ig_wait(container_id, tries=12, delay=3):
    for _ in range(tries):
        try:
            info = ig_call("GET", container_id, params={"fields": "status_code,status"})
        except RuntimeError:
            info = ig_call("GET", container_id, params={"fields": "status_code"})
        status = info.get("status_code")
        if status == "FINISHED":
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError("Instagram faylni qayta ishlay olmadi: " + str(info))
        time.sleep(delay)
    raise RuntimeError("Instagram faylni vaqtida qayta ishlamadi.")


def ig_publish(uid, container_id):
    ig_call("POST", f"{uid}/media_publish", data={"creation_id": container_id})


def ig_publish_image(image_url, caption):
    uid = ig_user_id()
    cid = ig_call("POST", f"{uid}/media", data={"image_url": image_url, "caption": caption})["id"]
    ig_wait(cid)
    ig_publish(uid, cid)


def ig_publish_reel_url(video_url, caption):
    uid = ig_user_id()
    cid = ig_call(
        "POST",
        f"{uid}/media",
        data={
            "media_type": "REELS",
            "video_url": video_url,
            "caption": caption,
            "share_to_feed": "true",
        },
    )["id"]
    ig_wait(cid, tries=30, delay=5)
    ig_publish(uid, cid)


def post_reel(title, caption, stamp):
    frame = f"/tmp/frame_{stamp}.jpg"
    repo_path = f"images/reel_{stamp}.mp4"
    make_reel_frame(title, frame)
    music = find_music()
    print("Musiqa:", music or "topilmadi (video ovozsiz bo'ladi)")
    make_video(frame, repo_path, music)
    print("Video tayyor:", os.path.getsize(repo_path) // 1024, "KB")
    url = publish_to_repo(repo_path, "images/reel_*.mp4", 6)
    print("Video havolasi tayyor, Instagramga yuborilmoqda...")
    ig_publish_reel_url(url, caption)
    print("Instagram Reels joylandi.")


def post_image(title, caption, stamp):
    path = f"images/card_{stamp}.jpg"
    make_card(title, path)
    url = publish_to_repo(path, "images/card_*.jpg", 15)
    ig_publish_image(url, caption)
    print("Instagramga rasm joylandi.")


def post_to_instagram(post, item):
    os.makedirs("images", exist_ok=True)
    stamp = datetime.now(TZ).strftime("%Y%m%d_%H%M%S")
    title = headline(post)
    caption = (
        strip_tags(post)
        + "\n\nManba: " + item["source"]
        + "\n\n\u26a0\ufe0f Bu moliyaviy maslahat emas."
        + "\n\n#trading #treyding #forex #kripto #moliya"
    )[:2200]
    fmt = os.environ.get("IG_FORMAT", "reel").strip().lower()  # reel | image | both
    reel_done = False
    if fmt in ("reel", "both"):
        try:
            post_reel(title, caption, stamp)
            reel_done = True
        except Exception as e:
            print("Reels joylanmadi:", e)
    if fmt in ("image", "both") or not reel_done:
        post_image(title, caption, stamp)


def parse_time(value):
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt


def run_once():
    manual = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
    history = load_history()
    now = datetime.now(TZ)

    # Jadval bir soatda bir necha marta ishga tushadi (GitHub ba'zilarini tashlab yuboradi).
    # Oxirgi post yaqinda bo'lgan bo'lsa, ortiqcha post qo'ymaymiz.
    try:
        min_gap = int(os.environ.get("MIN_GAP_MINUTES", "55"))
    except ValueError:
        min_gap = 55
    if not manual and history:
        last = parse_time(history[-1].get("time"))
        if last and now - last < timedelta(minutes=min_gap):
            mins = int((now - last).total_seconds() // 60)
            print(f"Oxirgi post {mins} daqiqa oldin joylangan, bu safar o'tkazib yuboriladi.")
            return

    last_ig = None
    for h in reversed(history):
        if h.get("ig"):
            last_ig = parse_time(h.get("time"))
            break

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
            "time": now.isoformat(),
            "summary": item["title"],
            "link": item["link"],
            "ig": False,
        }
    )
    save_history(history)
    print("Post joylandi:", item["title"])

    if not IG_TOKEN:
        print("IG_ACCESS_TOKEN yo'q, Instagram o'tkazib yuborildi.")
        return
    try:
        ig_gap = float(os.environ.get("IG_GAP_HOURS", "3"))
    except ValueError:
        ig_gap = 3.0
    due = last_ig is None or now - last_ig >= timedelta(hours=ig_gap, minutes=-15)
    if manual or due:
        try:
            post_to_instagram(post, item)
            history[-1]["ig"] = True
            save_history(history)
        except Exception as e:
            print("Instagram xatosi:", e)
    else:
        hrs = (now - last_ig).total_seconds() / 3600
        print(f"Bu safar Instagramga joylanmaydi: oxirgisi {hrs:.1f} soat oldin (kerak: {ig_gap} soat).")


if __name__ == "__main__":
    for attempt in range(3):
        try:
            run_once()
            break
        except Exception as e:
            print(f"Xato ({attempt + 1}/3): {e}")
            if attempt < 2:
                time.sleep(120)
    else:
        sys.exit(1)

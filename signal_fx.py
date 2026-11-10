"""Signal va chorlov Reels uchun motion-dizayn (1080x1920, 30 fps). Faqat Pillow + ffmpeg.

make_signal_reel: ticker, LONG/SHORT, narx zinapoyasi (stop / entry / targetlar ketma-ket chiziladi), R/R hisoblagich,
yakunda Telegram'ga chorlov. make_promo_reel: kanalga chorlov (jonli sham grafigi, kinetik matn, CTA).
Hech qanday foyda va'dasi yo'q; har kadrda "moliyaviy maslahat emas" ogohlantirishi turadi.
"""
from __future__ import annotations

import math
import random
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
NAVY, PANEL = (7, 12, 26), (16, 24, 46)
GREEN, RED, GOLD = (0, 214, 160), (255, 82, 98), (255, 196, 64)
WHITE, MUTED = (242, 246, 252), (150, 166, 190)
DISCLAIMER = "Moliyaviy maslahat emas. Savdo yuqori xavf bilan bog'liq."


# ---------------------------------------------------------------- yordamchilar
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def ease_out(t):
    return 1 - (1 - clamp(t)) ** 3


def ease_back(t):  # biroz "sakrab" to'xtash
    t, c = clamp(t), 1.70158
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def prog(t, start, dur):
    return clamp((t - start) / dur)


def mix(c1, c2, k):
    return tuple(int(a + (b - a) * k) for a, b in zip(c1, c2))


class Fonts:
    def __init__(self, paths):
        self.path = next((p for p in paths if _exists(p)), None)
        self.cache = {}

    def __call__(self, size):
        size = max(8, int(size))
        if size not in self.cache:
            self.cache[size] = ImageFont.truetype(self.path, size) if self.path else ImageFont.load_default()
        return self.cache[size]


def _exists(p):
    try:
        open(p, "rb").close()
        return True
    except OSError:
        return False


def text_c(d, cx, y, s, font, fill, alpha=1.0):
    """Markazlashgan matn; alpha<1 bo'lsa fon rangiga aralashtiriladi (shaffoflik o'rniga, tez)."""
    w = d.textlength(s, font=font)
    d.text((cx - w / 2, y), s, font=font, fill=mix(NAVY, fill, clamp(alpha)))


def fit(d, s, fonts, size, max_w):
    while size > 20 and d.textlength(s, font=fonts(size)) > max_w:
        size -= 4
    return fonts(size)


def fmt_price(p):
    s = f"{p:.8f}".rstrip("0").rstrip(".")
    return s if len(s) <= 10 else f"{p:.6g}"


def background(accent, seed=1):
    """Statik asos: gradient, panjara, yumshoq yorug'lik dog'lari (bir marta chiziladi)."""
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img)
    for y in range(0, H, 4):
        d.rectangle([0, y, W, y + 4], fill=mix(NAVY, (12, 20, 44), y / H))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    rnd = random.Random(seed)
    for _ in range(3):
        x, y, r = rnd.randrange(W), rnd.randrange(H), rnd.randrange(260, 460)
        g.ellipse([x - r, y - r, x + r, y + r], fill=mix((0, 0, 0), accent, 0.22))
    glow = glow.filter(ImageFilter.GaussianBlur(140))
    img = Image.blend(img, Image.composite(glow, img, glow.convert("L").point(lambda v: min(255, v * 3))), 0.55)
    d = ImageDraw.Draw(img)
    for x in range(0, W, 90):
        d.line([x, 0, x, H], fill=(18, 28, 54), width=1)
    for y in range(0, H, 90):
        d.line([0, y, W, y], fill=(18, 28, 54), width=1)
    return img


def chrome(d, fonts, brand, t, dur, accent):
    """Har kadrda: brend, ogohlantirish, pastda jarayon chizig'i."""
    d.rounded_rectangle([60, 70, 60 + 14, 70 + 56], radius=6, fill=accent)
    d.text((92, 72), brand, font=fonts(44), fill=WHITE)
    text_c(d, W / 2, H - 120, DISCLAIMER, fonts(28), MUTED)
    d.rectangle([0, H - 12, W, H], fill=(20, 30, 56))
    d.rectangle([0, H - 12, int(W * clamp(t / dur)), H], fill=accent)


def particles(d, t, accent, seed=7, n=26):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y0, sp, r = rnd.randrange(W), rnd.randrange(H), rnd.uniform(20, 70), rnd.choice([2, 2, 3, 4])
        y = (y0 - sp * t) % H
        d.ellipse([x - r, y - r, x + r, y + r], fill=mix(NAVY, accent, 0.35 + 0.25 * math.sin(t * 2 + x)))


def cta(d, fonts, t0, t, accent, channel):
    """Yakuniy chorlov kartasi: pastdan ko'tariladi, tugma "nafas oladi"."""
    k = ease_back(prog(t, t0, 0.6))
    if k <= 0:
        return
    y = int(H - 840 * k) + 120
    d.rounded_rectangle([70, y, W - 70, y + 520], radius=44, fill=PANEL, outline=accent, width=4)
    text_c(d, W / 2, y + 50, "Signallar birinchi bo'lib", fonts(52), WHITE)
    text_c(d, W / 2, y + 120, "Telegram kanalda chiqadi", fonts(52), WHITE)
    pulse = 1 + 0.035 * math.sin((t - t0) * 6)
    bw, bh = int(760 * pulse), int(130 * pulse)
    bx, by = (W - bw) // 2, y + 240 + (130 - bh) // 2
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=65, fill=accent)
    text_c(d, W / 2, by + bh / 2 - 34, "t.me/" + channel.lstrip("@"), fit(d, "t.me/" + channel, fonts, 60, bw - 80), NAVY)
    text_c(d, W / 2, y + 410, "Profildagi havola orqali qo'shiling", fonts(36), MUTED)


def encode(frames, out_path, ffmpeg, music, dur):
    """Kadrlarni ffmpeg'ga uzatadi (rawvideo -> h264), musiqa bo'lsa qo'shadi."""
    cmd = [ffmpeg, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if music:
        cmd += ["-stream_loop", "-1", "-i", music, "-af", f"afade=t=in:st=0:d=0.5,afade=t=out:st={dur - 1:.2f}:d=1,volume=0.8"]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    cmd += ["-t", f"{dur:.2f}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out_path]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for frame in frames:
        proc.stdin.write(frame.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError("ffmpeg xato")


# ---------------------------------------------------------------- signal reel
def make_signal_reel(sig: dict, brand: str, channel: str, out_path: str, ffmpeg: str, font_paths, music=None, when: str = "",
                     result: dict | None = None):
    """sig: {symbol, side, entry, targets[list], stop}. Davomiyligi 10 s.

    result berilsa natija videosi bo'ladi: {"target": bajarilgan target raqami yoki None, "pct": kanal yozgan foiz yoki None}.
    Foiz faqat narx o'zgarishi sifatida (leveragesiz) hisoblanadi yoki kanal xabaridan olingani aniq yoziladi.
    """
    fonts = Fonts(font_paths)
    dur = 10.0
    long_ = sig["side"] == "LONG"
    accent = GREEN if long_ else RED
    bg = background(accent, seed=sum(map(ord, sig["symbol"])))
    entry, stop, targets = sig["entry"], sig["stop"], list(sig["targets"])
    levels = [("STOP", stop, RED)] + [("KIRISH", entry, WHITE)] + [(f"TARGET {i + 1}", t, GREEN) for i, t in enumerate(targets)]
    lo, hi = min(p for _, p, _ in levels), max(p for _, p, _ in levels)
    top, bottom = 620, 1380

    def y_of(p):
        return bottom - (p - lo) / (hi - lo) * (bottom - top) if hi > lo else (top + bottom) / 2

    # yorliqlar ustma-ust tushmasligi uchun: narx bo'yicha tartiblab, orasini kamida 96 px qilamiz
    label_y, prev = {}, None
    for name, price, _ in sorted(levels, key=lambda l: -l[1]):
        y = y_of(price) if prev is None else max(y_of(price), prev + 96)
        label_y[name], prev = y, y
    shift = max(0, max(label_y.values()) - (bottom + 40))
    label_y = {k: v - shift for k, v in label_y.items()}

    rr = abs(targets[-1] - entry) / abs(entry - stop)
    hit = result.get("target") if result else None
    hit = hit if hit and 1 <= hit <= len(targets) else None
    lost = bool(result) and result.get("outcome") == "loss"
    hit = None if lost else hit
    path_end = stop if lost else targets[hit - 1] if hit else (None if result else targets[-1])
    ticker = sig["symbol"].replace("USDT", "")
    order = sorted(levels, key=lambda l: abs(l[1] - entry))  # entry birinchi, keyin yaqinidan uzog'iga
    order = [l for l in order if l[0] == "KIRISH"] + [l for l in order if l[0] == "STOP"] + [l for l in order if l[0].startswith("TARGET")]

    def frames():
        for i in range(int(dur * FPS)):
            t = i / FPS
            img = bg.copy()
            d = ImageDraw.Draw(img)
            particles(d, t, accent)
            chrome(d, fonts, brand, t, dur, accent)
            fade = 1 - prog(t, 7.0, 0.4)  # chorlov chiqqanda asosiy qism so'nadi
            # --- sarlavha: nishon + ticker + yo'nalish
            k = ease_back(prog(t, 0.1, 0.5))
            if k > 0 and fade > 0:
                bx = int(-500 + 560 * k)
                d.rounded_rectangle([bx, 190, bx + 420, 262], radius=36, fill=mix(NAVY, GOLD, fade))
                d.text((bx + 34, 204), "NATIJA" if result else "YANGI SIGNAL", font=fonts(40), fill=NAVY)
            k = ease_back(prog(t, 0.35, 0.6))
            if k > 0 and fade > 0:
                f = fit(d, "$" + ticker, fonts, int(170 * k), 640)
                d.text((60, 290), "$" + ticker, font=f, fill=mix(NAVY, WHITE, fade))
                pw = 300
                px = int(W + 20 - (pw + 80) * ease_out(prog(t, 0.6, 0.5)))
                d.rounded_rectangle([px, 330, px + pw, 440], radius=55, fill=mix(NAVY, accent, fade))
                text_c(d, px + pw / 2, 348, sig["side"], fonts(64), NAVY)
                if when:
                    d.text((64, 500), ("Signal berilgan vaqt: " if result else "Telegram'da berildi: ") + when, font=fonts(34), fill=mix(NAVY, MUTED, fade * ease_out(prog(t, 0.9, 0.4))))
            # --- narx zinapoyasi
            if fade > 0:
                for n, (name, price, color) in enumerate(order):
                    k = ease_out(prog(t, 1.3 + n * 0.55, 0.5))
                    if k <= 0:
                        continue
                    y = y_of(price)
                    x2 = 60 + (W - 380 - 60) * k
                    d.line([60, y, x2, y], fill=mix(NAVY, color, fade), width=6 if name == "KIRISH" else 4)
                    d.ellipse([x2 - 9, y - 9, x2 + 9, y + 9], fill=mix(NAVY, color, fade))
                    if k > 0.7:
                        a = fade * prog(k, 0.7, 0.3)
                        ly = label_y[name]
                        if abs(ly - y) > 4:  # yorliq surilgan bo'lsa, chiziq uchidan yorliqqa ingichka bog'lovchi
                            d.line([x2, y, W - 372, ly], fill=mix(NAVY, color, a * 0.6), width=2)
                        done = hit and name.startswith("TARGET") and int(name.split()[1]) <= hit
                        mark = " ✓" if done else " ✕" if lost and name == "STOP" else ""
                        d.text((W - 360, ly - 52), name + mark, font=fonts(30), fill=mix(NAVY, GOLD if done else RED if mark else MUTED, a))
                        d.text((W - 360, ly - 18), fmt_price(price), font=fonts(46), fill=mix(NAVY, color, a))
                        if name != "KIRISH":
                            pct = (price - entry) / entry * 100
                            d.text((W - 150, ly - 12), f"{pct:+.1f}%", font=fonts(32), fill=mix(NAVY, color, a))
                # --- reja yo'li: kirishdan oxirgi targetgacha yuradigan nuqta (reja, natija emas)
                t_path = 1.3 + len(order) * 0.55
                k = ease_out(prog(t, t_path, 1.6))
                if k > 0 and path_end is not None:
                    pts = [(140 + (W - 560) * j / 40, y_of(entry + (path_end - entry) * (j / 40) + (hi - lo) * 0.035 * math.sin(j * 1.3) * (1 - j / 40)))
                           for j in range(int(40 * k) + 1)]
                    if len(pts) > 1:
                        d.line(pts, fill=mix(NAVY, RED if lost else accent, fade), width=7, joint="curve")
                    x, y = pts[-1]
                    r = 16 + 5 * math.sin(t * 9)
                    d.ellipse([x - r, y - r, x + r, y + r], fill=mix(NAVY, WHITE, fade))
                # --- R/R hisoblagich
                k = ease_out(prog(t, t_path + 0.4, 1.0))
                if k > 0 and result:
                    tone = RED if lost else GOLD
                    d.rounded_rectangle([60, 1440, W - 60, 1620], radius=36, fill=mix(NAVY, PANEL, fade), outline=mix(NAVY, tone, fade), width=3)
                    left = "Stop-loss ishladi" if lost else f"Target {hit} bajarildi" if hit else "Foyda bilan yopildi"
                    d.text((100, 1470), "Natija", font=fonts(36), fill=mix(NAVY, MUTED, fade))
                    d.text((100, 1524), left, font=fit(d, left, fonts, 60, 500), fill=mix(NAVY, tone, fade))
                    if lost:
                        move = abs(stop - entry) / entry * 100
                        d.text((650, 1470), "Narx o'zgarishi", font=fonts(36), fill=mix(NAVY, MUTED, fade))
                        d.text((650, 1520), f"-{move * k:.1f}%", font=fonts(76), fill=mix(NAVY, RED, fade))
                    elif hit:
                        move = abs(targets[hit - 1] - entry) / entry * 100
                        d.text((650, 1470), "Narx o'zgarishi", font=fonts(36), fill=mix(NAVY, MUTED, fade))
                        d.text((650, 1520), f"+{move * k:.1f}%", font=fonts(76), fill=mix(NAVY, GREEN, fade))
                    elif result.get("pct"):
                        d.text((650, 1470), "Kanal xabarida", font=fonts(36), fill=mix(NAVY, MUTED, fade))
                        d.text((650, 1520), result["pct"], font=fit(d, result["pct"], fonts, 76, 330), fill=mix(NAVY, GREEN, fade))
                elif k > 0:
                    d.rounded_rectangle([60, 1440, W - 60, 1620], radius=36, fill=mix(NAVY, PANEL, fade))
                    d.text((100, 1470), "Risk / Reward", font=fonts(36), fill=mix(NAVY, MUTED, fade))
                    d.text((100, 1520), f"1 : {rr * k:.2f}", font=fonts(76), fill=mix(NAVY, GOLD, fade))
                    risk = abs(entry - stop) / entry * 100
                    d.text((620, 1470), "Stopgacha", font=fonts(36), fill=mix(NAVY, MUTED, fade))
                    d.text((620, 1520), f"{risk * k:.1f}%", font=fonts(76), fill=mix(NAVY, RED, fade))
            cta(d, fonts, 7.1, t, accent, channel)
            yield img

    encode(frames(), out_path, ffmpeg, music, dur)


# ---------------------------------------------------------------- chorlov (promo) reel
PROMO_LINES = [
    ("Har kuni savdo signallari", "Kirish, targetlar va stop aniq ko'rsatiladi"),
    ("Kripto va oltin tahlili", "Muhim narx darajalari o'zbek tilida"),
    ("Bozor yangiliklari", "Narxga ta'sir qiladigan xabarlar qisqa va tushunarli"),
]


def make_promo_reel(brand: str, channel: str, out_path: str, ffmpeg: str, font_paths, music=None, seed: int = 0):
    """Telegram kanalga chorlov. Davomiyligi 9 s: jonli sham grafigi + 3 ta kinetik qator + CTA."""
    fonts = Fonts(font_paths)
    dur = 9.0
    rnd = random.Random(seed)
    accent = rnd.choice([GREEN, GOLD, (90, 170, 255)])
    bg = background(accent, seed=seed + 3)
    # tasodifiy, lekin o'sib boruvchi sham grafigi (bezak; real narx emas)
    candles, price = [], 100.0
    for _ in range(26):
        o = price
        price += rnd.uniform(-2.2, 3.4)
        c = price
        candles.append((o, c, max(o, c) + rnd.uniform(0.3, 1.6), min(o, c) - rnd.uniform(0.3, 1.6)))
    lo, hi = min(c[3] for c in candles), max(c[2] for c in candles)
    top, bottom = 420, 1000

    def y_of(p):
        return bottom - (p - lo) / (hi - lo) * (bottom - top)

    def frames():
        for i in range(int(dur * FPS)):
            t = i / FPS
            img = bg.copy()
            d = ImageDraw.Draw(img)
            particles(d, t, accent, seed=seed + 11)
            chrome(d, fonts, brand, t, dur, accent)
            fade = 1 - prog(t, 6.2, 0.4)
            if fade > 0:
                shown = prog(t, 0.2, 2.6) * len(candles)
                for n, (o, c, hi_, lo_) in enumerate(candles):
                    k = clamp(shown - n)
                    if k <= 0:
                        break
                    x = 90 + n * 35
                    col = mix(NAVY, GREEN if c >= o else RED, fade)
                    cc = o + (c - o) * ease_out(k)
                    d.line([x + 11, y_of(hi_), x + 11, y_of(lo_)], fill=col, width=3)
                    d.rectangle([x, min(y_of(o), y_of(cc)), x + 22, max(y_of(o), y_of(cc)) + 2], fill=col)
                k = ease_back(prog(t, 0.2, 0.6))
                text_c(d, W / 2, 220, "Treyding o'zbek tilida", fit(d, "Treyding o'zbek tilida", fonts, int(72 * max(k, 0.01)), W - 120), mix(NAVY, WHITE, fade))
                for n, (head, sub) in enumerate(PROMO_LINES):
                    k = ease_out(prog(t, 1.2 + n * 1.3, 0.5))
                    if k <= 0:
                        continue
                    y = 1080 + n * 170
                    x = int(-W + (W + 70) * k)
                    d.rounded_rectangle([x, y, x + W - 140, y + 140], radius=30, fill=mix(NAVY, PANEL, fade))
                    d.rounded_rectangle([x, y, x + 12, y + 140], radius=6, fill=mix(NAVY, accent, fade))
                    d.text((x + 44, y + 22), head, font=fit(d, head, fonts, 48, W - 240), fill=mix(NAVY, WHITE, fade))
                    d.text((x + 44, y + 84), sub, font=fit(d, sub, fonts, 30, W - 240), fill=mix(NAVY, MUTED, fade))
            cta(d, fonts, 6.3, t, accent, channel)
            yield img

    encode(frames(), out_path, ffmpeg, music, dur)

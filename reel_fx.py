"""Animatsion Instagram Reels: harakatlanuvchi fon + qatorma-qator sarlavha + asosiy raqam + manba + CTA.

Fon: PIXABAY_API_KEY bo'lsa mavzuga mos sinematik stok video (birja ekrani, kripto, shahar),
bo'lmasa harakatlanuvchi "trading terminal" uslubidagi fon (to'r, yorug'lik dog'lari) chiziladi.
Faqat Pillow + ffmpeg kerak.
"""
import os
import random
import re
import subprocess
import tempfile

W, H, FPS, DUR = 1080, 1920, 30, 14.0
NAVY = (8, 14, 28)
ACCENT = (0, 214, 160)
WHITE = (242, 246, 252)
MUTED = (160, 176, 196)

CATEGORIES = [
    ("KRIPTO", ("bitcoin", "btc", "ethereum", "eth", "crypto", "kripto", "binance", "coin", "token", "blockchain", "solana", "xrp")),
    ("OLTIN VA XOMASHYO", ("gold", "oltin", "oil", "neft", "silver", "kumush", "brent", "commodit")),
    ("VALYUTA", ("dollar", "dollarr", "euro", "yevro", "rubl", "so'm", "forex", "currency", "valyuta", "yuan", "yen")),
    ("AKSIYALAR", ("stock", "aksiya", "shares", "nasdaq", "s&p", "dow", "earnings", "ipo", "tesla", "apple", "nvidia", "microsoft")),
    ("IQTISOD", ("fed", "inflation", "inflyatsiya", "rate", "stavka", "gdp", "yaim", "bank", "economy", "iqtisod", "tariff", "tarif")),
]
BROLL = {
    "KRIPTO": ["bitcoin", "cryptocurrency", "blockchain technology", "digital money"],
    "OLTIN VA XOMASHYO": ["gold bars", "oil refinery", "gold"],
    "VALYUTA": ["money counting", "currency exchange", "dollar bills"],
    "AKSIYALAR": ["stock market", "trading screen", "stock exchange"],
    "IQTISOD": ["financial district", "city skyline night", "business people city"],
    "BOZOR YANGILIGI": ["stock market", "trading screen", "city skyline night"],
}


def category(text: str) -> str:
    low = text.lower()
    for name, words in CATEGORIES:
        # so'z boshidan solishtiramiz: "reaksiya" ichidagi "aksiya" hisoblanmasin
        if any(re.search(r"(?<![a-z'])" + re.escape(w), low) for w in words):
            return name
    return "BOZOR YANGILIGI"


def key_number(text: str) -> str | None:
    """Sarlavhadagi eng ko'zga tashlanadigan raqam: $6.34 billion, 12%, 100 000 ... ."""
    m = re.search(r"\$\s?\d[\d.,]*\s?(trillion|billion|million|trln|mlrd|mln|bn|[tbmk])?\b", text, re.I)
    if m:
        s = re.sub(r"\s+", "", m.group(0))
        return (s.replace("billion", "B").replace("million", "M").replace("trillion", "T")
                 .replace("mlrd", "B").replace("mln", "M").replace("trln", "T"))
    m = re.search(r"[-+]?\d[\d.,]*\s?%", text)
    if m:
        return m.group(0).replace(" ", "")
    m = re.search(r"\b\d{1,3}(?:[ ,.]\d{3})+\b|\b\d{4,}\b", text)
    if m and not re.fullmatch(r"(19|20)\d\d", m.group(0)):
        return m.group(0)
    return None




# ---------------- uslub: har Reels boshqacha ----------------
# Rang, joylashuv, paydo bo'lish va fon harakati navbatma-navbat almashadi; oldingi Reels uslubi
# LAST_STYLE_FILE'da saqlanadi va keyingisi undan farq qiladi.
PALETTES = [
    {"name": "teal", "accent": (0, 214, 160), "navy": (8, 14, 28)},
    {"name": "gold", "accent": (255, 196, 0), "navy": (14, 12, 22)},
    {"name": "blue", "accent": (64, 156, 255), "navy": (6, 12, 30)},
    {"name": "violet", "accent": (150, 110, 255), "navy": (12, 10, 28)},
]
LAYOUTS = ["left", "center", "lower", "split"]  # "breaking" faqat ALERT_WORDS bo'lsa
ENTRANCES = ["rise", "slide", "drop"]
MOTIONS = ["drift", "zoom", "pan"]
ALERT_WORDS = ("rekord", "record", "keskin", "favqulodda", "emergency", "crash", "qulab")
LAST_STYLE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_reel_style.json")

# vaqt va o'lchamlar (px). Xavfsiz zona: tepada 250, pastda 420, yonlarda 80 px bo'sh.
END_AT = DUR - 3.6           # shu paytda asosiy matn o'chib, yakuniy karta chiqadi
SAFE_X, SAFE_TOP, SAFE_BOTTOM = 80, 250, H - 420
TICKER_Y, TICKER_H, TICKER_SPEED = 262, 56, 130
BADGE_Y = 340
HEAD_Y = {"lower": 640, "split": 470}
SPLIT_CARD_BOTTOM, CARD_H = SAFE_BOTTOM - 150, 210


def has_alert(text: str) -> bool:
    low = text.lower()
    return any(re.search(r"(?<![a-z'])" + w, low) for w in ALERT_WORDS)


def load_last_style(path=LAST_STYLE_FILE) -> dict:
    try:
        import json
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_last_style(style, path=LAST_STYLE_FILE) -> None:
    try:
        import json
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"palette": style["palette"]["name"], "layout": style["layout"],
                       "entrance": style["entrance"], "motion": style["motion"]}, fh)
    except OSError as e:
        print("Oxirgi uslub saqlanmadi:", e)


def _differ(rng, options, last):
    """Variantlardan birini tanlaydi, oldingisini (agar boshqa tanlov bo'lsa) chetlab o'tadi."""
    fresh = [o for o in options if o != last]
    return rng.choice(fresh or options)


def pick_style(rng=None, title="", last=None):
    rng = rng or random.Random()
    last = load_last_style() if last is None else last
    alert = has_alert(title or "")
    palette = _differ(rng, [p["name"] for p in PALETTES], last.get("palette"))
    layout = _differ(rng, LAYOUTS + (["breaking"] if alert else []), last.get("layout"))
    if alert and last.get("layout") != "breaking":
        layout = "breaking"
    return {"palette": next(p for p in PALETTES if p["name"] == palette), "layout": layout,
            "entrance": _differ(rng, ENTRANCES, last.get("entrance")),
            "motion": _differ(rng, MOTIONS, last.get("motion"))}


# ---------------- rasm qatlamlari ----------------
def _font(size, font_paths):
    from PIL import ImageFont
    for p in font_paths:
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap(draw, text, font, max_w):
    lines, line = [], ""
    for word in text.split():
        t = (line + " " + word).strip()
        if draw.textlength(t, font=font) <= max_w:
            line = t
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _layer(path, draw_fn, size=(W, H), blur=10):
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(img), ImageDraw.Draw(shadow))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    Image.alpha_composite(shadow, img).save(path)


def _fit_font(draw, text, size, min_size, max_w, bold):
    while size > min_size and draw.textlength(text, font=bold(size)) > max_w:
        size -= 2
    return bold(size)


def _fit_headline(probe, title, bold, layout, has_num):
    """Eng katta shrift: <=6 qator va raqam kartasi xavfsiz zonadan chiqmaydi."""
    y0 = HEAD_Y.get(layout, 450)
    card_room = 0 if layout == "split" else (CARD_H + 90 if has_num else 0)
    limit = (SPLIT_CARD_BOTTOM - CARD_H - 40) if layout == "split" and has_num else SAFE_BOTTOM - 120 - card_room
    for fs in (86, 78, 70, 62, 56, 50):
        f = bold(fs)
        lines = _wrap(probe, title, f, W - 2 * 90)
        lh = int(fs * 1.22)
        if len(lines) <= 6 and y0 + len(lines) * lh <= limit:
            break
    if len(lines) > 6:
        lines = lines[:6]
        lines[-1] = lines[-1].rstrip(" .,") + "…"
    lh = int(fs * 1.22)
    y0 = max(450, min(y0, limit - len(lines) * lh))
    return f, lines, lh, y0


def build_layers(tmp, title, source, brand, font_paths, style=None):
    """(layers, cat, meta). layers: dict(path, start, fade, kind). Barcha matn xavfsiz zonada."""
    from PIL import Image, ImageDraw
    style = style or {"palette": PALETTES[0], "layout": "left"}
    ACCENT, NAVY = style["palette"]["accent"], style["palette"]["navy"]
    layout = style["layout"]
    center = layout == "center"
    cat, num = category(title), key_number(title)
    bold = lambda s: _font(s, font_paths)
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    layers, meta = [], {}

    def add(name, fn, start, fade, kind="text", size=(W, H), blur=10):
        p = os.path.join(tmp, f"l_{name}.png")
        _layer(p, fn, size, blur)
        layers.append({"path": p, "start": start, "fade": fade, "kind": kind})

    def lx(txt, f):
        return (W - probe.textlength(txt, font=f)) / 2 if center else 90

    # 1) yorliq yoki "MUHIM" banneri
    def badge(d, sd):
        f = bold(40)
        if layout == "breaking":
            txt = f"MUHIM   |   {cat}"
            f = _fit_font(probe, txt, 40, 28, W - 2 * SAFE_X - 70, bold)
            d.rounded_rectangle([SAFE_X, BADGE_Y, W - SAFE_X, BADGE_Y + 72], radius=14, fill=ACCENT + (255,))
            d.text((SAFE_X + 35, BADGE_Y + 12), txt, font=f, fill=NAVY + (255,))
            return
        txt = f"● {cat}"
        tw = d.textlength(txt, font=f)
        x0 = (W - tw - 56) / 2 if center else SAFE_X
        d.rounded_rectangle([x0, BADGE_Y, x0 + tw + 56, BADGE_Y + 72], radius=36, fill=ACCENT + (255,))
        d.text((x0 + 28, BADGE_Y + 12), txt, font=f, fill=NAVY + (255,))
    add("badge", badge, 0.3, 0.4)

    # 2) sarlavha qatorlari
    f, lines, lh, y0 = _fit_headline(probe, title, bold, layout, bool(num))
    for i, ln in enumerate(lines):
        def line(d, sd, ln=ln, y=y0 + i * lh):
            x = lx(ln, f)
            sd.text((x + 2, y + 4), ln, font=f, fill=(0, 0, 0, 230))
            d.text((x, y), ln, font=f, fill=WHITE + (255,))
        add(f"line{i}", line, 0.9 + i * 0.45, 0.35)
    y_after = y0 + len(lines) * lh + 30
    t_lines = 0.9 + len(lines) * 0.45

    # 3) aksent chiziq (fx rejimida ffmpeg uni chizib chiqadi)
    bar_w = 320
    bar_x = (W - bar_w) // 2 if center else 90
    meta["bar"] = {"x": bar_x, "y": y_after, "w": bar_w, "start": t_lines}
    add("bar", lambda d, sd: d.rectangle([bar_x, y_after, bar_x + bar_w, y_after + 10], fill=ACCENT + (255,)),
        t_lines, 0.3, kind="bar")

    # 4) asosiy raqam kartasi: alohida kichik PNG (masshtab animatsiyasi uchun), aksent nur bilan
    if num:
        m = 70
        f_num = _fit_font(probe, num, 150 if len(num) <= 7 else 112, 60, W - 2 * SAFE_X - 80, bold)
        cw = int(probe.textlength(num, font=f_num)) + 80
        top = SPLIT_CARD_BOTTOM - CARD_H if layout == "split" else y_after + 50
        left = (W - cw) // 2 if center or layout == "split" else SAFE_X
        meta["card"] = {"cx": left + cw / 2, "cy": top + CARD_H / 2, "w": cw + 2 * m, "h": CARD_H + 2 * m}

        def big(d, sd):
            sd.rounded_rectangle([m, m, m + cw, m + CARD_H], radius=28, fill=ACCENT + (120,))
            d.rounded_rectangle([m, m, m + cw, m + CARD_H], radius=28, fill=(255, 255, 255, 240))
            d.rectangle([m + 24, m + CARD_H - 14, m + cw - 24, m + CARD_H - 8], fill=ACCENT + (255,))
            d.text((m + 40, m + 14), num, font=f_num, fill=NAVY + (255,))
        add("num", big, t_lines + 0.5, 0.2, kind="card", size=(cw + 2 * m, CARD_H + 2 * m), blur=28)
        meta["card"]["start"] = t_lines + 0.5

    # 5) manba va brend (pastki xavfsiz chegaradan oldin tugaydi)
    def foot(d, sd):
        f1, f2 = bold(36), bold(44)
        if source:
            t1 = f"Manba: {source}"
            f1 = _fit_font(probe, t1, 36, 24, W - 2 * SAFE_X, bold)
            d.text((lx(t1, f1), SAFE_BOTTOM - 100), t1, font=f1, fill=MUTED + (255,))
        t2 = "@" + brand
        d.text((lx(t2, f2), SAFE_BOTTOM - 52), t2, font=f2, fill=ACCENT + (255,))
    add("foot", foot, 1.2, 0.5)

    # 6) yakuniy karta: qorong'i parda + brend + CTA (asosiy matn o'chgach chiqadi)
    def end(d, sd):
        d.rectangle([0, 0, W, H], fill=NAVY + (205,))
        tag = f"● {cat}"
        ft = bold(38)
        tw = d.textlength(tag, font=ft)
        d.rounded_rectangle([(W - tw) / 2 - 28, 640, (W + tw) / 2 + 28, 704], radius=32, outline=ACCENT + (255,), width=3)
        d.text(((W - tw) / 2, 649), tag, font=ft, fill=ACCENT + (255,))
        name = "@" + brand
        fb = _fit_font(d, name, 96, 48, W - 2 * SAFE_X, bold)
        d.text(((W - d.textlength(name, font=fb)) / 2, 740), name, font=fb, fill=WHITE + (255,))
        d.rectangle([(W - 240) / 2, 890, (W + 240) / 2, 900], fill=ACCENT + (255,))
        txt = "To'liq tahlil Telegram kanalda"
        fc = _fit_font(d, txt, 52, 30, W - 2 * SAFE_X - 80, bold)
        cw_ = d.textlength(txt, font=fc)
        x = (W - cw_) / 2
        d.rounded_rectangle([x - 40, 960, x + cw_ + 40, 1070], radius=55, fill=ACCENT + (255,))
        d.text((x, 960 + (110 - fc.size * 1.2) / 2), txt, font=fc, fill=NAVY + (255,))
    add("end", end, END_AT + 0.25, 0.5, kind="end")
    return layers, cat, meta


# ---------------- fon va effekt PNG'lari ----------------
def _procedural_bg(tmp, accent=(0, 214, 160), navy=NAVY):
    """Harakatlanuvchi 'terminal' foni: sekin suriluvchi to'r + yorug'lik dog'lari (ffmpeg uchun PNG'lar).
    Faqat bezak: to'r chiziqlari va nur; haqiqiy narx chizig'iga o'xshash narsa chizilmaydi."""
    from PIL import Image, ImageDraw, ImageFilter
    base = Image.new("RGB", (W, H), navy)
    d = ImageDraw.Draw(base)
    for y in range(H):  # vertikal gradient
        t = y / H
        d.line([(0, y), (W, y)], fill=(int(navy[0] + 10 * t), int(navy[1] + 18 * t), int(navy[2] + 30 * t)))
    glow = Image.new("RGB", (W, H), (0, 0, 0))
    g = ImageDraw.Draw(glow)
    for _ in range(5):
        cx, cy, r = random.randint(0, W), random.randint(0, H), random.randint(220, 420)
        col = random.choice([tuple(int(c * 0.55) for c in accent), (20, 60, 140), (0, 90, 120)])
        g.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    base = Image.blend(base, glow, 0.45)
    base_p = os.path.join(tmp, "bg_base.png"); base.save(base_p)
    grid = Image.new("RGBA", (W, H + 240), (0, 0, 0, 0))
    gd = ImageDraw.Draw(grid)
    for x in range(0, W, 120):
        gd.line([(x, 0), (x, H + 240)], fill=(120, 200, 255, 22), width=2)
    for y in range(0, H + 240, 120):
        gd.line([(0, y), (W, y)], fill=(120, 200, 255, 22), width=2)
    grid_p = os.path.join(tmp, "bg_grid.png"); grid.save(grid_p)
    return base_p, grid_p


def _fx_pngs(tmp, accent, navy, cat, brand, alert, font_paths):
    """Ticker lentasi + maskasi, yorug'lik chizig'i va supurish PNG'i. Ticker matni: faqat kategoriya va brend."""
    from PIL import Image, ImageDraw
    f = _font(30, font_paths)
    parts = (["MUHIM"] if alert else []) + [cat, "@" + brand, "BOZOR YANGILIGI"]
    seg = "".join(f"{p}   ●   " for p in parts)
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    period = int(probe.textlength(seg, font=f)) + 10
    reps = (W + period) // period + 2
    strip = Image.new("RGBA", (period * reps, TICKER_H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(strip)
    for i in range(reps):
        sd.text((i * period, 10), seg, font=f, fill=WHITE + (255,))
    sd.rectangle([0, 0, strip.width, 2], fill=accent + (255,))
    sd.rectangle([0, TICKER_H - 3, strip.width, TICKER_H], fill=accent + (255,))
    strip_p = os.path.join(tmp, "fx_strip.png"); strip.save(strip_p)
    mask = Image.new("L", (W, TICKER_H), 0)  # chetlarda so'nadi: matn yon xavfsiz zonasidan chiqmaydi
    md = ImageDraw.Draw(mask)
    for x in range(W):
        a = min(1.0, max(0.0, (min(x, W - 1 - x) - SAFE_X) / 90))
        md.line([(x, 0), (x, TICKER_H)], fill=int(215 * a))
    mask_p = os.path.join(tmp, "fx_mask.png"); mask.save(mask_p)
    scan = Image.new("RGBA", (W, 260), (0, 0, 0, 0))
    sc = ImageDraw.Draw(scan)
    for y in range(260):
        a = max(0.0, 1 - abs(y - 130) / 130) ** 2
        sc.line([(0, y), (W, y)], fill=accent + (int(70 * a),))
    sc.line([(0, 130), (W, 130)], fill=accent + (110,), width=2)
    scan_p = os.path.join(tmp, "fx_scan.png"); scan.save(scan_p)
    sweep_w, shear = 520, int(H * 0.28)
    row = Image.new("RGBA", (sweep_w, 1))
    row.putdata([accent + (int(48 * (1 - abs(x - sweep_w / 2) / (sweep_w / 2)) ** 2),) for x in range(sweep_w)])
    band = row.resize((sweep_w, H)).transform((sweep_w + shear, H), Image.AFFINE, (1, shear / H, 0, 0, 1, 0))
    sweep_p = os.path.join(tmp, "fx_sweep.png"); band.save(sweep_p)
    return {"strip": strip_p, "mask": mask_p, "scan": scan_p, "sweep": sweep_p, "period": period,
            "sweep_w": band.width}

def _pixabay_bg(tmp, cat):
    import requests
    key = os.environ.get("PIXABAY_API_KEY", "").strip()
    if not key:
        return None
    q = random.choice(BROLL.get(cat, BROLL["BOZOR YANGILIGI"]))
    try:
        r = requests.get("https://pixabay.com/api/videos/", timeout=30, params={
            "key": key, "q": q, "per_page": 30, "safesearch": "true", "order": "popular"})
        r.raise_for_status()
        hits = [h for h in r.json().get("hits", []) if h.get("duration", 0) >= 8]
        hits.sort(key=lambda h: h.get("likes", 0) + h.get("downloads", 0) / 50, reverse=True)
        for h in hits[:8]:
            f = (h.get("videos") or {}).get("large") or (h.get("videos") or {}).get("medium") or {}
            if f.get("url") and f.get("height", 0) >= 720:
                path = os.path.join(tmp, "bg.mp4")
                with requests.get(f["url"], stream=True, timeout=120) as resp:
                    resp.raise_for_status()
                    with open(path, "wb") as fh:
                        for chunk in resp.iter_content(1 << 20):
                            fh.write(chunk)
                print(f"Fon video: Pixabay '{q}' ({h['id']})")
                return path
    except Exception as e:  # noqa: BLE001
        print("Pixabay fon olinmadi:", e)
    return None



# ---------------- yig'ish ----------------
def _pop_scale(st):
    """Raqam kartasi: kichikdan sakrab (1.12) joyiga o'tiradi."""
    return (f"if(lt(t,{st:.2f}),0.55,if(lt(t,{st + 0.28:.2f}),0.55+0.57*(t-{st:.2f})/0.28,"
            f"if(lt(t,{st + 0.45:.2f}),1.12-0.12*(t-{st + 0.28:.2f})/0.17,1)))")


def _background(style, accent, bg_video, tmp, add_input):
    """Fon filtri ([bg] belgisigacha). Ikkinchi qiymat: fon kirishlari soni."""
    if bg_video:
        add_input(["-stream_loop", "-1", "-t", f"{DUR:.1f}", "-i", bg_video])
        move = {
            "drift": f"scale={W + 80}:{H + 140},crop={W}:{H}:x='40+30*sin(t/3)':y='70*(t/{DUR})'",
            "pan": f"scale={W + 80}:{H + 220},crop={W}:{H}:x=40:y='220*(1-t/{DUR})'",
            "zoom": (f"scale=w='trunc({W}*(1.04+0.10*t/{DUR})/2)*2':h='trunc({H}*(1.04+0.10*t/{DUR})/2)*2'"
                     f":eval=frame,crop={W}:{H}"),
        }[style["motion"]]
        return (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
                f"eq=brightness=-0.22:saturation=0.85,gblur=sigma=3,{move},setsar=1[bg]")
    base_p, grid_p = _procedural_bg(tmp, accent, style["palette"]["navy"])
    add_input(["-loop", "1", "-framerate", str(FPS), "-t", f"{DUR:.1f}", "-i", base_p])
    add_input(["-loop", "1", "-framerate", str(FPS), "-t", f"{DUR:.1f}", "-i", grid_p])
    return ("[0:v]format=rgba,zoompan=z='1+0.0004*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d=1:s={W}x{H}:fps={FPS}[b0];[1:v]format=rgba[gr];"
            "[b0][gr]overlay=0:'-mod(t*24,120)':format=auto,setsar=1[bg]")


def _render(tmp, title, source, brand, out_path, ffmpeg, font_paths, music, style, fx):
    accent = style["palette"]["accent"]
    acc_hex = "0x%02X%02X%02X" % accent
    layers, cat, meta = build_layers(tmp, title, source, brand, font_paths, style)
    bg_video = _pixabay_bg(tmp, cat) if not os.path.exists(os.path.join(tmp, "bg.mp4")) else os.path.join(tmp, "bg.mp4")
    d = f"{DUR:.1f}"
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    n_inputs = [0]

    def add_input(args):
        cmd.extend(args)
        n_inputs[0] += 1

    def add_png(path):
        add_input(["-loop", "1", "-framerate", str(FPS), "-t", d, "-i", path])
        return n_inputs[0] - 1

    f = [_background(style, accent, bg_video, tmp, add_input)]
    fxp = _fx_pngs(tmp, accent, style["palette"]["navy"], cat, brand, style["layout"] == "breaking",
                   font_paths) if fx else None
    idx = [add_png(l["path"]) for l in layers]
    if fx:
        i_strip, i_mask, i_sweep = add_png(fxp["strip"]), add_png(fxp["mask"]), add_png(fxp["sweep"])
        i_scan = add_png(fxp["scan"]) if not bg_video else None
    if music:
        add_input(["-stream_loop", "-1", "-i", music])
    else:
        add_input(["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"])
    ai = n_inputs[0] - 1

    cur = "v0"
    f.append("[bg]vignette=PI/4.8" + (",format=yuv420p,noise=alls=7:allf=t" if fx else "") + f"[{cur}]")

    def chain(expr, nxt):
        nonlocal cur
        f.append(expr.replace("{IN}", f"[{cur}]") + f"[{nxt}]")
        cur = nxt

    if fx and i_scan is not None:  # fon ustida sekin pastga tushuvchi yorug'lik chizig'i
        chain(f"{{IN}}[{i_scan}:v]overlay=0:'mod(t*150,{H + 260})-260':format=auto", "vs")
    if fx:  # yuqoridagi yugurib o'tuvchi lenta
        f.append(f"color=c=0x0A1020:s={W}x{TICKER_H}:r={FPS}:d={d},format=rgba[tkc]")
        f.append(f"[tkc][{i_strip}:v]overlay=x='-mod(t*{TICKER_SPEED},{fxp['period']})':y=0:format=auto[tks]")
        f.append(f"[{i_mask}:v]format=gray[tkg]")
        f.append("[tks][tkg]alphamerge[tkm]")
        chain(f"{{IN}}[tkm]overlay=0:{TICKER_Y}:format=auto", "vt")

    for i, l in enumerate(layers):
        st, fin, kind = l["start"], l["fade"], l["kind"]
        if kind == "bar" and fx:
            continue
        sig = f"[{idx[i]}:v]format=rgba,fade=t=in:st={st:.2f}:d={fin:.2f}:alpha=1"
        if kind != "end":
            sig += f",fade=t=out:st={END_AT:.2f}:d=0.4:alpha=1"
        k = f"max(0,1-(t-{st:.2f})/{fin:.2f})"
        if kind == "card" and fx:
            c = meta["card"]
            sig += (f",scale=w='max(2,trunc({c['w']}*({_pop_scale(st)})/2)*2)':"
                    f"h='max(2,trunc({c['h']}*({_pop_scale(st)})/2)*2)':eval=frame")
            f.append(sig + f"[s{i}]")
            chain(f"{{IN}}[s{i}]overlay=x='{c['cx']:.1f}-overlay_w/2':y='{c['cy']:.1f}-overlay_h/2':format=auto", f"v{i + 1}")
            continue
        f.append(sig + f"[s{i}]")
        xy = "0:0" if kind in ("end", "card") else {
            "rise": f"0:'40*{k}'", "slide": f"'-60*{k}':0", "drop": f"0:'-40*{k}'"}[style["entrance"]]
        chain(f"{{IN}}[s{i}]overlay={xy}:format=auto", f"v{i + 1}")

    tail = []
    if fx:  # sarlavha tagidagi chiziq chapdan o'ngga chiziladi, so'ng yorug'lik supurib o'tadi
        b = meta["bar"]
        tail.append(f"drawbox=x={b['x']}:y={b['y']}:w='clip({b['w']}*(t-{b['start']:.2f})/0.5,0,{b['w']})':h=10:"
                    f"color={acc_hex}@1:t=fill:enable='between(t,{b['start']:.2f},{END_AT + 0.4:.2f})'")
    tail.append(f"drawbox=x=0:y={H - 12}:w='iw*t/{DUR}':h=12:color={acc_hex}@1:t=fill")
    chain("{IN}" + ",".join(tail), "vb")
    if fx:
        chain(f"{{IN}}[{i_sweep}:v]overlay=x='-{fxp['sweep_w']}+({W}+{fxp['sweep_w']})*(t-0.9)/0.9':y=0:"
              "enable='between(t,0.9,1.8)':format=auto", "vw")
    f.append(f"[{cur}]fade=t=in:st=0:d=0.4,fade=t=out:st={DUR - 0.6:.2f}:d=0.6,format=yuv420p[v]")
    cmd += ["-filter_complex", ";".join(f), "-map", "[v]", "-map", f"{ai}:a",
            "-af", f"afade=t=in:d=0.8,afade=t=out:st={DUR - 1.5:.1f}:d=1.5", "-t", d,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out_path


def make_reel(title, source, brand, out_path, ffmpeg, font_paths, music=None, style=None):
    auto_style = style is None
    style = style or pick_style(title=title)
    print(f"Reels uslubi: {style['palette']['name']}, {style['layout']}, {style['entrance']}, {style['motion']}")
    tmp = tempfile.mkdtemp(prefix="reel_")
    try:
        _render(tmp, title, source, brand, out_path, ffmpeg, font_paths, music, style, fx=True)
    except subprocess.CalledProcessError as e:
        # yangi effekt filtri ishlamasa: oddiy (effektsiz) variantda qayta yasaymiz
        print("Premium effektlar ishlamadi, oddiy uslub:", (e.stderr or "")[-400:])
        _render(tmp, title, source, brand, out_path, ffmpeg, font_paths, music, style, fx=False)
    if auto_style:
        save_last_style(style)
    return out_path

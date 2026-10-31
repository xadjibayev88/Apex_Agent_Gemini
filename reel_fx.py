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
# Rang aksenti, matn joylashuvi, paydo bo'lish yo'nalishi va fon harakati har safar tasodifan tanlanadi,
# shuning uchun ketma-ket Reels bir xil qolipda chiqmaydi (4 x 3 x 3 x 3 = 108 xil ko'rinish).
PALETTES = [
    {"name": "teal", "accent": (0, 214, 160), "navy": (8, 14, 28)},
    {"name": "gold", "accent": (255, 196, 0), "navy": (14, 12, 22)},
    {"name": "blue", "accent": (64, 156, 255), "navy": (6, 12, 30)},
    {"name": "violet", "accent": (150, 110, 255), "navy": (12, 10, 28)},
]
LAYOUTS = ["left", "center", "lower"]
ENTRANCES = ["rise", "slide", "drop"]
MOTIONS = ["drift", "zoom", "pan"]


def pick_style(rng=None):
    rng = rng or random.Random()
    return {"palette": rng.choice(PALETTES), "layout": rng.choice(LAYOUTS),
            "entrance": rng.choice(ENTRANCES), "motion": rng.choice(MOTIONS)}


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


def _layer(path, draw_fn, h=H):
    from PIL import Image, ImageDraw, ImageFilter
    img = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    shadow = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    draw_fn(ImageDraw.Draw(img), ImageDraw.Draw(shadow))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    Image.alpha_composite(shadow, img).save(path)


def build_layers(tmp, title, source, brand, font_paths, style=None):
    """[(png, start, fade_in)] qatlamlar ro'yxati."""
    from PIL import Image, ImageDraw
    style = style or {"palette": PALETTES[0], "layout": "left"}
    ACCENT, NAVY = style["palette"]["accent"], style["palette"]["navy"]
    center = style["layout"] == "center"

    def lx(d, txt, f):
        """Matnning x nuqtasi: chapdan 90 px yoki markazda."""
        return (W - d.textlength(txt, font=f)) / 2 if center else 90

    layers = []
    cat = category(title)
    num = key_number(title)
    bold = lambda s: _font(s, font_paths)

    # 1) yuqoridagi yorliq
    def badge(d, sd):
        f = bold(40)
        txt = f"● {cat}"
        tw = d.textlength(txt, font=f)
        x0 = (W - tw - 56) / 2 if center else 80
        d.rounded_rectangle([x0, 300, x0 + tw + 56, 372], radius=36, fill=ACCENT + (255,))
        d.text((x0 + 28, 312), txt, font=f, fill=NAVY + (255,))
    p = os.path.join(tmp, "l_badge.png"); _layer(p, badge); layers.append((p, 0.3, 0.4))

    # 2) sarlavha qatorlari
    probe = ImageDraw.Draw(Image.new("RGBA", (W, H)))
    for fs in (86, 78, 70, 62, 56, 50):
        f = bold(fs)
        lines = _wrap(probe, title, f, W - 180)
        if len(lines) <= (5 if num else 6):
            break
    lines = lines[:6]
    lh = int(fs * 1.22)
    y0 = 430 if style["layout"] != "lower" else 640
    for i, ln in enumerate(lines):
        def line(d, sd, ln=ln, y=y0 + i * lh, f=f):
            x = lx(d, ln, f)
            sd.text((x + 2, y + 4), ln, font=f, fill=(0, 0, 0, 230))
            d.text((x, y), ln, font=f, fill=WHITE + (255,))
        p = os.path.join(tmp, f"l_line{i}.png"); _layer(p, line); layers.append((p, 0.9 + i * 0.45, 0.35))
    y_after = y0 + len(lines) * lh + 30

    # 3) aksent chiziq
    def bar(d, sd, y=y_after):
        x0 = (W - 210) / 2 if center else 90
        d.rectangle([x0, y, x0 + 210, y + 10], fill=ACCENT + (255,))
    p = os.path.join(tmp, "l_bar.png"); _layer(p, bar); t_lines = 0.9 + len(lines) * 0.45
    layers.append((p, t_lines, 0.3))

    # 4) asosiy raqam kartasi
    if num:
        def big(d, sd, y=y_after + 60):
            f = bold(150 if len(num) <= 7 else 112)
            tw = d.textlength(num, font=f)
            x0 = (W - tw - 80) / 2 if center else 80
            d.rounded_rectangle([x0, y, x0 + tw + 80, y + 210], radius=28, fill=(255, 255, 255, 235))
            d.text((x0 + 40, y + 22), num, font=f, fill=NAVY + (255,))
        p = os.path.join(tmp, "l_num.png"); _layer(p, big); layers.append((p, t_lines + 0.5, 0.3))

    # 5) manba va brend
    def foot(d, sd):
        f1, f2 = bold(36), bold(44)
        if source:
            t1 = f"Manba: {source}"
            d.text((lx(d, t1, f1), H - 470), t1, font=f1, fill=MUTED + (255,))
        t2 = "@" + brand
        d.text((lx(d, t2, f2), H - 400), t2, font=f2, fill=ACCENT + (255,))
    p = os.path.join(tmp, "l_foot.png"); _layer(p, foot); layers.append((p, 1.2, 0.5))

    # 6) yakuniy chaqiriq (raqam kartasi bilan ustma-ust tushmasin)
    card_bottom = y_after + (60 + 210 if num else 0)
    cta_y = min(max(H - 640, card_bottom + 40), H - 590)
    # "lower" joylashuvda raqam kartasi pastga tushadi: CTA va manba bilan to'qnashsa, karta oldingi joyga qaytadi
    if style["layout"] == "lower" and card_bottom + 40 > H - 640:
        return build_layers(tmp, title, source, brand, font_paths, {**style, "layout": "left"})

    def cta(d, sd, top=cta_y):
        f = bold(52)
        txt = "To'liq tahlil Telegram kanalda"
        tw = d.textlength(txt, font=f)
        x = (W - tw) / 2
        d.rounded_rectangle([x - 40, top, x + tw + 40, top + 100], radius=50, fill=NAVY + (235,), outline=ACCENT + (255,), width=4)
        d.text((x, top + 16), txt, font=f, fill=WHITE + (255,))
    p = os.path.join(tmp, "l_cta.png"); _layer(p, cta); layers.append((p, DUR - 3.2, 0.4))
    return layers, cat


# ---------------- fon ----------------
def _procedural_bg(tmp, accent=(0, 214, 160), navy=NAVY):
    """Harakatlanuvchi 'terminal' foni: sekin suriluvchi to'r + yorug'lik dog'lari (ffmpeg uchun PNG'lar)."""
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
def make_reel(title, source, brand, out_path, ffmpeg, font_paths, music=None, style=None):
    tmp = tempfile.mkdtemp(prefix="reel_")
    style = style or pick_style()
    accent = style["palette"]["accent"]
    acc_hex = "0x%02X%02X%02X" % accent
    print(f"Reels uslubi: {style['palette']['name']}, {style['layout']}, {style['entrance']}, {style['motion']}")
    layers, cat = build_layers(tmp, title, source, brand, font_paths, style)
    bg_video = _pixabay_bg(tmp, cat)
    d = f"{DUR:.1f}"
    cmd = [ffmpeg, "-y", "-loglevel", "error"]
    if bg_video:
        cmd += ["-stream_loop", "-1", "-t", d, "-i", bg_video]
        move = {
            "drift": f"scale={W + 80}:{H + 140},crop={W}:{H}:x='40+30*sin(t/3)':y='70*(t/{DUR})'",
            "pan": f"scale={W + 80}:{H + 220},crop={W}:{H}:x=40:y='220*(1-t/{DUR})'",
            "zoom": (f"scale=w='trunc({W}*(1.04+0.10*t/{DUR})/2)*2':h='trunc({H}*(1.04+0.10*t/{DUR})/2)*2'"
                     f":eval=frame,crop={W}:{H}"),
        }[style["motion"]]
        bg = (f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
              "eq=brightness=-0.22:saturation=0.85,gblur=sigma=3,"
              f"{move},setsar=1[bg]")
        n_bg = 1
    else:
        base_p, grid_p = _procedural_bg(tmp, accent, style["palette"]["navy"])
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", d, "-i", base_p,
                "-loop", "1", "-framerate", str(FPS), "-t", d, "-i", grid_p]
        bg = ("[0:v]format=rgba,zoompan=z='1+0.0004*on':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
              f":d=1:s={W}x{H}:fps={FPS}[b0];[1:v]format=rgba[gr];"
              f"[b0][gr]overlay=0:'-mod(t*24,120)':format=auto,setsar=1[bg]")
        n_bg = 2
    for p, *_ in layers:
        cmd += ["-loop", "1", "-framerate", str(FPS), "-t", d, "-i", p]
    ai = n_bg + len(layers)
    if music:
        cmd += ["-stream_loop", "-1", "-i", music]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100"]
    f = [bg, "[bg]vignette=PI/4.8[v0]"]
    for i, (p, st, fin) in enumerate(layers):
        idx = n_bg + i
        # paydo bo'lish + uslubga qarab pastdan / chapdan / yuqoridan surilish
        f.append(f"[{idx}:v]format=rgba,fade=t=in:st={st:.2f}:d={fin:.2f}:alpha=1[s{i}]")
        k = f"max(0,1-(t-{st:.2f})/{fin:.2f})"
        xy = {"rise": f"0:'40*{k}'", "slide": f"'-60*{k}':0", "drop": f"0:'-40*{k}'"}[style["entrance"]]
        f.append(f"[v{i}][s{i}]overlay={xy}:format=auto[v{i + 1}]")
    n = len(layers)
    f.append(f"[v{n}]drawbox=x=0:y={H - 12}:w='iw*t/{DUR}':h=12:color={acc_hex}@1:t=fill,"
             f"fade=t=in:st=0:d=0.4,fade=t=out:st={DUR - 0.6:.2f}:d=0.6,format=yuv420p[v]")
    cmd += ["-filter_complex", ";".join(f), "-map", "[v]", "-map", f"{ai}:a",
            "-af", f"afade=t=in:d=0.8,afade=t=out:st={DUR - 1.5:.1f}:d=1.5", "-t", d,
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart", out_path]
    subprocess.run(cmd, check=True)
    return out_path

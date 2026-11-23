#!/usr/bin/env python3
"""Instagram carousel (1080x1350) for a fixture list (cup round, new schedule...) in the v2 look.

Usage: python3 fixtures_carousel.py <fixtures.json> <out_dir>

Slides: cover (photo + banner + swipe chip) -> one slide per group of matches (crest cards with date and time)
-> whole schedule on one slide ("save it") -> comment question with options + follow card.
"""
import json, math, os, random, sys
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

import build as B

CW, CH = 1080, 1350
MX = 60                                    # side margin (the profile grid shows the middle 1012px)
_m = ImageDraw.Draw(Image.new("L", (1, 1)))
font = B.font


# ---------------------------------------------------------------- shared look (same as v2.py)
def background():
    img = Image.new("RGB", (CW, CH)); d = ImageDraw.Draw(img)
    for y in range(CH):
        t = abs(y / CH - 0.40) * 1.5
        d.line([(0, y), (CW, y)], fill=tuple(int(a + (b - a) * min(1, t)) for a, b in zip(B.BG1, B.BG2)))
    n = Image.effect_noise((CW, CH), 30).convert("L").point(lambda v: v // 14)
    img = Image.composite(Image.new("RGB", (CW, CH), (40, 70, 75)), img, n).convert("RGBA")
    deco = Image.new("RGBA", (CW, CH), (0, 0, 0, 0)); d = ImageDraw.Draw(deco)

    def dots(cx, cy, sx, sy, reach=480, alpha=70):
        for gx in range(0, reach, 20):
            for gy in range(0, int(reach * 0.55), 20):
                r = 6.5 - math.hypot(gx, gy * 1.6) / 80
                if r > 0.8:
                    x, y = cx + sx * gx, cy + sy * gy
                    d.ellipse((x - r, y - r, x + r, y + r), fill=B.GREEN + (alpha,))

    def stripes(x, y, n, length, width, gap, alpha, flip=1):
        for i in range(n):
            ox = x + i * gap * flip
            d.polygon([(ox, y), (ox + width * flip, y), (ox + (width - length) * flip, y + length),
                       (ox - length * flip, y + length)], fill=B.GREEN + (alpha,))
    stripes(-60, -60, 4, 200, 24, 42, 140)
    dots(CW - 10, 10, -1, 1)
    dots(10, CH - 10, 1, -1)
    stripes(CW + 30, CH - 240, 5, 240, 24, 42, 160, -1)
    glow = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((-200, CH - 220, CW + 200, CH + 220), fill=B.GREEN + (38,))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(80)))
    img.alpha_composite(deco)
    return img


def bar_img(text, f, fill, txt=None, skew=24, padx=30, hpad=1.2):
    tw = _m.textlength(text, font=f); bh = int(f.size * hpad); bw = int(tw + 2 * padx + skew)
    im = Image.new("RGBA", (bw + 30, bh + 34), (0, 0, 0, 0))
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).polygon([(skew + 8, 14), (bw + 8, 14), (bw - skew + 8, bh + 14), (8, bh + 14)], fill=(0, 0, 0, 150))
    im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(9)))
    d = ImageDraw.Draw(im)
    d.polygon([(skew, 0), (bw, 0), (bw - skew, bh), (0, bh)], fill=fill + (255,))
    d.text((skew / 2 + padx, bh / 2 + 3), text, font=f, fill=txt or B.INK, anchor="lm")
    return im


def banner(tag, headline, size=96, maxw=900):
    """Dark tag with yellow text + one skewed bar per line (white, green when the line has [highlight])."""
    lines = [(ln.replace("[", "").replace("]", ""), "[" in ln) for ln in headline]
    f = font(B.F_BLACK_I, size)
    while f.size > 50 and max(_m.textlength(t, font=f) + 84 + 26 * i for i, (t, _) in enumerate(lines)) > maxw:
        f = font(B.F_BLACK_I, f.size - 2)
    parts = []
    y = 0
    if tag:
        tg = bar_img(tag, font(B.F_XB_I, 36), (8, 22, 28), B.YELLOW, skew=16, padx=22, hpad=1.45)
        parts.append((tg, (0, 0))); y = tg.height - 34 + 8
    for i, (t, hl) in enumerate(lines):
        bi = bar_img(t, f, B.GREEN if hl else B.WHITE)
        parts.append((bi, (10 + 26 * i, y))); y += bi.height - 34 + 6
    L = Image.new("RGBA", (max(x + im.width for im, (x, _) in parts), y + 34), (0, 0, 0, 0))
    for im, xy in parts: L.alpha_composite(im, xy)
    return L, y


class Look:
    def __init__(self, cfg):
        rnd = random.Random(7)
        t = B.title_layer(rnd); self.title = t.resize((380, int(t.height * 380 / t.width)), Image.LANCZOS)
        lg = Image.open(os.path.join(B.HERE, cfg.get("logo", "assets/logo.png"))).convert("RGBA")
        self.logo = lg.resize((280, int(lg.height * 280 / lg.width)), Image.LANCZOS)
        self.bg = background()

    def base(self):
        img = self.bg.copy()
        img.alpha_composite(self.title, (MX, 44))
        img.alpha_composite(self.logo, (CW - MX - self.logo.width, 44 + (self.title.height - self.logo.height) // 2 + 4))
        self.top = 44 + self.title.height + 26
        ImageDraw.Draw(img).line([(MX, self.top - 12), (CW - MX, self.top - 12)], fill=B.GREEN + (70,), width=2)
        return img


def footer(img, i, n, swipe=True):
    d = ImageDraw.Draw(img); f = font(B.F_XB_I, 30)
    d.text((MX, CH - 54), f"{i:02d}/{n:02d}", font=f, fill=(170, 200, 205), anchor="lm")
    if swipe:
        t = "ΣΥΡΕ"; tw = d.textlength(t, font=f); x1 = CW - MX
        ax = x1 - 34; ay = CH - 54
        d.text((ax - 14 - tw, ay), t, font=f, fill=B.GREEN, anchor="lm")
        d.polygon([(ax, ay - 12), (ax + 30, ay), (ax, ay + 12)], fill=B.GREEN)


def photo(path, w, h, focus=(0.5, 0.5)):
    im = Image.open(path).convert("RGB")
    k = max(w / im.width, h / im.height)
    im = im.resize((int(im.width * k) + 1, int(im.height * k) + 1), Image.LANCZOS)
    l = int((im.width - w) * focus[0]); t = int((im.height - h) * focus[1])
    im = im.crop((l, t, l + w, t + h))
    im = ImageEnhance.Contrast(im).enhance(1.08); im = ImageEnhance.Color(im).enhance(1.1)
    return im.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=2)).convert("RGBA")


def fade(w, h, top=0, bottom=0, alpha=255):
    f = Image.new("RGBA", (w, h), (0, 0, 0, 0)); d = ImageDraw.Draw(f)
    for y in range(h):
        a = 0
        if bottom and y > h - bottom: a = int(alpha * ((y - (h - bottom)) / bottom) ** 1.4)
        if top and y < top: a = max(a, int(alpha * (1 - y / top) ** 1.4))
        d.line([(0, y), (w, y)], fill=B.BG2 + (a,))
    return f


# ---------------------------------------------------------------- match card
def match_card(m, width=960, n=2):
    """Crests + names on the sides, date over a big kick-off time in the middle (bigger when the slide has fewer matches)."""
    big = n == 1
    h, cs = {1: (400, 230), 2: (300, 150)}.get(n, (206, 88))
    im = Image.new("RGBA", (width + 40, h + 70), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    ox, oy = 20, 40
    d.rounded_rectangle((ox, oy, ox + width, oy + h), 32, fill=(8, 22, 28, 205))
    if m.get("hot"):
        d.rounded_rectangle((ox, oy, ox + width, oy + h), 32, outline=B.GREEN + (255,), width=4)
    if m.get("label"):                                           # e.g. ΝΤΕΡΜΠΙ on the top edge
        lf = font(B.F_XB_I, 34); lw = int(d.textlength(m["label"], font=lf)) + 60
        B.para(d, (ox + (width - lw) / 2, oy - 26), lw, 52, 12, B.YELLOW)
        d.text((ox + width / 2, oy), m["label"], font=lf, fill=B.INK, anchor="mm")
    side_w = 300
    for side, cx in (("home", ox + side_w / 2 + 10), ("away", ox + width - side_w / 2 - 10)):
        cy_crest = oy + (36 if big else 20 if n == 2 else 12)
        if m.get(side + "_logo"):
            c = B.crest_img(m[side + "_logo"], cs); im.alpha_composite(c, (int(cx - c.width / 2), cy_crest - 6))
        nf = font(B.F_BLACK_I, 50 if big else 42 if n == 2 else 38)
        while nf.size > 26 and d.textlength(m[side], font=nf) > side_w - 10: nf = font(B.F_BLACK_I, nf.size - 2)
        d.text((cx, oy + h - (50 if big else 40 if n == 2 else 28)), m[side], font=nf, fill=B.WHITE, anchor="mm", stroke_width=3, stroke_fill=B.INK)
    mid = ox + width / 2
    df = font(B.F_XB_I, 44 if big else 36 if n == 2 else 32)
    d.text((mid, oy + h * 0.30), m["when"], font=df, fill=B.YELLOW, anchor="mm", stroke_width=2, stroke_fill=B.INK)
    tf = font(B.F_BLACK_I, 150 if big else 110 if n == 2 else 84)
    d.text((mid, oy + h * 0.58), m["time"], font=tf, fill=B.WHITE, anchor="mm", stroke_width=4, stroke_fill=B.INK)
    return im


# ---------------------------------------------------------------- slides
def cover(cfg, L, i, n):
    c = cfg["cover"]; img = L.base(); top = L.top
    ph_h = c.get("photo_h", 720)
    if c.get("image"):
        ph = photo(os.path.join(B.HERE, c["image"]), CW, ph_h, tuple(c.get("focus", (0.5, 0.5))))
        ph.alpha_composite(fade(CW, ph_h, top=60, bottom=320))
        img.alpha_composite(ph, (0, top))
    bn, bh = banner(c.get("tag"), c["headline"], size=c.get("size", 118))
    by = top + ph_h - 190
    img.alpha_composite(bn, (MX - 14, by))
    y = by + bh + 26
    d = ImageDraw.Draw(img)
    for ln in c.get("sub", []):
        d.text((MX, y), ln, font=font(B.F_XB_I, 46), fill=B.WHITE, anchor="lm", stroke_width=3, stroke_fill=B.INK); y += 60
    if c.get("swipe"):
        f = font(B.F_XB_I, 40); tw = d.textlength(c["swipe"], font=f)
        w, hh = int(tw + 130), 76; x = MX; yy = y + 26
        d.rounded_rectangle((x, yy, x + w, yy + hh), hh // 2, fill=B.GREEN + (255,))
        d.text((x + 40, yy + hh / 2 + 1), c["swipe"], font=f, fill=B.INK, anchor="lm")
        ax = x + 40 + tw + 24; ay = yy + hh / 2
        d.polygon([(ax, ay - 15), (ax + 36, ay), (ax, ay + 15)], fill=B.INK)
        d.rectangle((ax - 20, ay - 5, ax + 4, ay + 5), fill=B.INK)
    return img


def group(s, cfg, L, i, n):
    img = L.base(); top = L.top + 20
    ms = s["matches"]
    bn, bh = banner(s.get("tag"), s["headline"], size=s.get("size", 100 if len(ms) < 3 else 84))
    img.alpha_composite(bn, (MX - 14, top))
    cards = [match_card(m, n=len(ms)) for m in ms]
    y0 = top + bh + 30; avail = CH - 100 - y0
    tot = sum(c.height - 40 for c in cards)
    gap = max(8, min(40, (avail - tot) / max(1, len(cards))))
    y = y0 + max(0, (avail - tot - gap * (len(cards) - 1)) / 2) - 20
    for c in cards:
        img.alpha_composite(c, ((CW - c.width) // 2, int(y))); y += c.height - 40 + gap
    footer(img, i, n)
    return img


def summary(cfg, L, i, n):
    sm = cfg["summary"]; img = L.base(); top = L.top + 20
    bn, bh = banner(sm.get("tag"), sm["headline"], size=sm.get("size", 92))
    img.alpha_composite(bn, (MX - 14, top))
    d = ImageDraw.Draw(img)
    rows = [m for s in cfg["slides"] for m in s["matches"]]
    rh = 92; y = top + bh + 28
    y = min(y, CH - 110 - rh * len(rows) - (50 if sm.get("note") else 0))
    cx = (MX + 150 + CW - MX) / 2; colw = cx - (MX + 150) - 92
    for m in rows:
        d.rounded_rectangle((MX, y, CW - MX, y + rh - 10), 18, fill=(8, 22, 28, 205))
        cy = y + (rh - 10) / 2
        d.text((MX + 26, cy - 15), m["short_date"], font=font(B.F_BLACK_I, 34), fill=B.YELLOW, anchor="lm")
        d.text((MX + 26, cy + 19), m["time"], font=font(B.F_XB_I, 28), fill=(200, 215, 220), anchor="lm")
        hn, an = m.get("home_s", m["home"]), m.get("away_s", m["away"])
        f = font(B.F_BLACK_I, 40)
        while f.size > 26 and max(d.textlength(hn, font=f), d.textlength(an, font=f)) > colw: f = font(B.F_BLACK_I, f.size - 2)
        d.text((cx - 26, cy + 2), hn, font=f, fill=B.WHITE, anchor="rm")
        d.text((cx, cy + 2), "–", font=f, fill=B.GREEN, anchor="mm")
        d.text((cx + 26, cy + 2), an, font=f, fill=B.WHITE, anchor="lm")
        hc = B.crest_img(m["home_logo"], 58); img.alpha_composite(hc, (int(MX + 150), int(cy - hc.height / 2 + 4)))
        ac = B.crest_img(m["away_logo"], 58); img.alpha_composite(ac, (int(CW - MX - 18 - ac.width + 20), int(cy - ac.height / 2 + 4)))
        y += rh
    if sm.get("note"):
        d.text((CW / 2, y + 18), sm["note"], font=font(B.F_XB_I, 32), fill=(200, 215, 220), anchor="mm")
    footer(img, i, n)
    return img


def cta(cfg, L, i, n):
    c = cfg["cta"]; img = L.base(); top = L.top + 20
    t = bar_img(c.get("title", "ΓΡΑΨΕ ΣΤΑ ΣΧΟΛΙΑ"), font(B.F_XB_I, 42), (8, 22, 28), B.YELLOW, skew=16, padx=22, hpad=1.45)
    img.alpha_composite(t, (MX - 14, top))
    em = B.emoji_img("👇", 58); img.alpha_composite(em, (MX - 14 + t.width - 14, top + 2))
    y = top + t.height - 34 + 22
    qf = font(B.F_BLACK_I, 78); d = ImageDraw.Draw(img)
    for ln in [w for p in c["question"].split("\n") for w in B.wrap(p, qf, CW - 2 * MX)]:
        d.text((MX, y), ln, font=qf, fill=B.WHITE, stroke_width=4, stroke_fill=B.INK); y += int(qf.size * 1.05)
    y += 24
    for emo, label in c["options"]:
        blk = bar_img("    ", font(B.F_BLACK_I, 64), (8, 22, 28), skew=20, padx=26)
        e = B.emoji_img(emo, 60)
        blk.alpha_composite(e, ((blk.width - 30 - e.width) // 2 + 2, (blk.height - 34 - e.height) // 2))
        f = font(B.F_BLACK_I, 60)
        while f.size > 36 and _m.textlength(label, font=f) + 120 > CW - 2 * MX - blk.width: f = font(B.F_BLACK_I, f.size - 2)
        row = bar_img(label, f, B.WHITE, skew=20, padx=30)
        img.alpha_composite(blk, (MX - 4, int(y))); img.alpha_composite(row, (MX - 4 + blk.width - 40, int(y + (blk.height - row.height) / 2)))
        y += blk.height - 34 + 16
    # follow card (same as the reel's end card)
    k = B.follow_card(cfg)
    card = k["card"].copy(); bx, by, bw, bh = k["btn"]
    card.alpha_composite(k["follow"], (bx, by)); card.alpha_composite(k["plus"], k["av_badge"])
    comp = Image.new("RGBA", k["shadow"].size, (0, 0, 0, 0))
    comp.paste((0, 0, 0, 255), (0, 0), k["shadow"]); comp.alpha_composite(card, (k["pad"], k["pad"]))
    fy = max(y + 190, CH - 290)
    B.place(img, k["glow"], CW / 2, fy, 0.9, 0.5)
    B.place(img, comp, CW / 2, fy, 0.9)
    B.place(img, k["pointer"], CW / 2 + 300, fy + 150, 0.9, 1.0, 8)
    B.place(img, k["bell"], CW / 2 + 360, fy - 130, 0.9, 1.0, -12)
    footer(img, i, n, swipe=False)
    return img


def make(src, out_dir):
    cfg = json.load(open(src, encoding="utf-8"))
    L = Look(cfg)
    n = 1 + len(cfg["slides"]) + (1 if cfg.get("summary") else 0) + 1
    slides = [cover(cfg, L, 1, n)]
    for s in cfg["slides"]: slides.append(group(s, cfg, L, len(slides) + 1, n))
    if cfg.get("summary"): slides.append(summary(cfg, L, len(slides) + 1, n))
    slides.append(cta(cfg, L, len(slides) + 1, n))
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i, im in enumerate(slides, 1):
        p = os.path.join(out_dir, f"{i:02d}.jpg"); im.convert("RGB").save(p, quality=95); paths.append(p)
    return paths


if __name__ == "__main__":
    for p in make(sys.argv[1], sys.argv[2]): print(p)

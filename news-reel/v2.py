"""«ΠΑΣΑ στα ΝΕΑ» v2 look (script.json: "layout": "v2").

What changes against the original renderer in build.py:
- Safe-zone layout: nothing important under the Instagram/TikTok UI (top bar, right icons, bottom caption).
  Clean header at y≈222 (logotype left, kouponaki right, small date next to the progress bar), photo ≈1100px tall
  from under the header down to the captions (y≈1460), per-photo "focus": [x, y], "fit": "contain" for graphics with text.
- Progress bar (one segment per story) under the header.
- Push transitions with motion blur and a green wipe band (no empty frames), whoosh on every change.
- Photos: colour grade + vignette, Ken Burns that alternates direction, several photos per story
  ("images": [{"src", "at"}] switch when the voice says the word "at").
- Stat callouts ("stat": {"value", "label", "at", "side": "left"|"right"}): badge that pops (count-up for numbers) with a pop sound.
- Captions: 2–3 words that pop in, active word on a green highlight.
- Clean end card (numbered headlines) under the follow pop-up; cover image for the profile grid.
"""
import math, os, re, subprocess
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

HEAD_Y, PHB, CAP_Y, TR = 222, 1500, 1460, 0.32     # PHB: full-bleed photo height (from y=0)


def _clamp(x, a=0.0, b=1.0): return max(a, min(b, x))
def _inout(t): t = _clamp(t); return 4 * t ** 3 if t < 0.5 else 1 - (-2 * t + 2) ** 3 / 2


def render(B, cfg, segments, audio, FT, video, rnd, intro_video, intro_start, out):
    W, H, FPS = B.W, B.H, B.FPS
    font = B.font
    sfx = {}

    # ---------------------------------------------------------------- static parts
    def background():
        img = Image.new("RGB", (W, H)); d = ImageDraw.Draw(img)
        for y in range(H):
            t = abs(y / H - 0.42) * 1.5
            d.line([(0, y), (W, y)], fill=tuple(int(a + (b - a) * min(1, t)) for a, b in zip(B.BG1, B.BG2)))
        n = Image.effect_noise((W, H), 30).convert("L").point(lambda v: v // 14)
        img = Image.composite(Image.new("RGB", (W, H), (40, 70, 75)), img, n).convert("RGBA")
        deco = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(deco)
        def dots(cx, cy, sx, sy, reach=520, alpha=80):        # halftone that fades away from a corner
            for gx in range(0, reach, 20):
                for gy in range(0, int(reach * 0.55), 20):
                    r = 6.5 - math.hypot(gx, gy * 1.6) / 85
                    if r > 0.8:
                        x, y = cx + sx * gx, cy + sy * gy
                        d.ellipse((x - r, y - r, x + r, y + r), fill=B.GREEN + (alpha,))
        def stripes(x, y, n, length, width, gap, alpha, flip=1):
            for i in range(n):
                ox = x + i * gap * flip
                d.polygon([(ox, y), (ox + width * flip, y), (ox + (width - length) * flip, y + length),
                           (ox - length * flip, y + length)], fill=B.GREEN + (alpha,))
        # top: stripes left, halftone right, thin accent line
        stripes(-40, -40, 4, 250, 26, 44, 150)
        dots(W - 10, 10, -1, 1)
        d.line([(0, 206), (W, 206)], fill=B.GREEN + (60,), width=2)
        # bottom: halftone left, stripes right, soft green glow
        dots(10, H - 10, 1, -1)
        stripes(W + 30, H - 330, 5, 330, 26, 44, 170, -1)
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse((-200, H - 260, W + 200, H + 260), fill=B.GREEN + (40,))
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(80)))
        img.alpha_composite(deco)
        # kicker in the top band (decor only: it sits under the app's top bar)
        kick = cfg.get("kicker", "ΚΥΠΡΙΑΚΟ ΠΟΔΟΣΦΑΙΡΟ"); kf = font(B.F_BOLD, 34); dd = ImageDraw.Draw(img)
        tot = sum(dd.textlength(c, font=kf) for c in kick) + 9 * (len(kick) - 1); x = (W - tot) / 2
        for c in kick:
            dd.text((x, 150), c, font=kf, fill=(170, 200, 205)); x += dd.textlength(c, font=kf) + 9
        return img

    title = B.title_layer(rnd); title = title.resize((400, int(title.height * 400 / title.width)), Image.LANCZOS)
    badge = B.date_badge(B.reel_date(cfg), w=78, h=96) if cfg.get("show_date", True) else None
    lg = Image.open(os.path.join(B.HERE, cfg.get("logo", "assets/logo.png"))).convert("RGBA")
    logo_s = lg.resize((290, int(lg.height * 290 / lg.width)), Image.LANCZOS)
    TH = title.height
    PROG_Y = HEAD_Y + TH + 22
    d0 = B.reel_date(cfg)
    date_txt = f"{B.GR_DAYS[d0.weekday()]} {d0.day:02d} {B.GR_MONTHS[d0.month - 1]}" if cfg.get("show_date", True) else ""
    df = font(B.F_XB_I, 30)
    DATE_W = int(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(date_txt, font=df)) + 22 if date_txt else 0

    def header(img):
        img.alpha_composite(title, (46, HEAD_Y))
        img.alpha_composite(logo_s, (1024 - logo_s.width, HEAD_Y + (TH - logo_s.height) // 2 + 4))
        if date_txt:
            ImageDraw.Draw(img).text((48, PROG_Y + 4), date_txt, font=df, fill=(205, 220, 225), anchor="lm")

    bg_plain = background()
    base = bg_plain.copy(); header(base)
    stories = [s for k, s in segments if k == "story"]
    NS = len(stories)

    def progress(img, k, frac):
        d = ImageDraw.Draw(img)
        x0, x1, gap = 46 + DATE_W, 1024, 12
        w = (x1 - x0 - gap * (NS - 1)) / max(1, NS)
        for i in range(NS):
            a = x0 + i * (w + gap)
            d.rounded_rectangle((a, PROG_Y, a + w, PROG_Y + 8), 4, fill=(255, 255, 255, 70))
            f = 1.0 if i < k else (frac if i == k else 0.0)
            if f > 0: d.rounded_rectangle((a, PROG_Y, a + max(8, w * f), PROG_Y + 8), 4, fill=B.GREEN + (255,))

    # ---------------------------------------------------------------- photos
    def grade(im):
        im = ImageEnhance.Contrast(im).enhance(1.08)
        im = ImageEnhance.Color(im).enhance(1.12)
        return im.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))

    PY = PROG_Y + 24                    # photo starts right under the header / progress bar
    PHP = PHB - PY                      # ...and runs down to the captions (≈1100px)
    BW, BH = int(W * 1.12), int(PHP * 1.12)
    def load_photo(path, focus=None, fit=None):
        im = Image.open(path).convert("RGB")
        if fit == "contain":   # graphics with text: whole image at the top, blurred copy fills the rest
            cov = im.resize((int(im.width * max(BW / im.width, BH / im.height)) + 1, int(im.height * max(BW / im.width, BH / im.height)) + 1), Image.LANCZOS)
            l, t = (cov.width - BW) // 2, (cov.height - BH) // 2
            canvas = ImageEnhance.Brightness(cov.crop((l, t, l + BW, t + BH)).filter(ImageFilter.GaussianBlur(28))).enhance(0.55)
            fg = im.resize((BW, int(im.height * BW / im.width)), Image.LANCZOS)
            canvas.paste(fg, (0, int(BH * 0.06)))
            return grade(canvas)
        k = max(BW / im.width, BH / im.height)
        im = im.resize((int(im.width * k) + 1, int(im.height * k) + 1), Image.LANCZOS)
        fx, fy = focus or (0.5, 0.45)
        l = int(_clamp(fx * im.width - BW / 2, 0, im.width - BW)); t = int(_clamp(fy * im.height - BH / 2, 0, im.height - BH))
        return grade(im.crop((l, t, l + BW, t + BH)))

    overlay = Image.new("RGBA", (W, PHP), (0, 0, 0, 0)); od = ImageDraw.Draw(overlay)
    for y in range(PHP):
        a = int(120 * (1 - y / 50)) if y < 50 else 0                         # soft edge under the progress bar
        if y > PHP - 520: a = max(a, int(255 * ((y - (PHP - 520)) / 520) ** 1.5))   # into the headline / captions
        od.line([(0, y), (W, y)], fill=B.BG2 + (a,))
    vig = Image.new("L", (W, PHP), 0); vd = ImageDraw.Draw(vig)
    for i in range(70):                                       # soft side vignette
        vd.rectangle((i, 0, W - 1 - i, PHP), outline=int(120 * (1 - i / 70) ** 2))
    overlay.alpha_composite(Image.merge("RGBA", (Image.new("L", (W, PHP), 0),) * 3 + (vig,)))
    canvas0 = bg_plain

    def kb_crop(im, u, idx):
        """Ken Burns: zoom in on even photos, out on odd ones, with a slight pan."""
        z = 1.0 + 0.10 * (u if idx % 2 == 0 else 1 - u)
        cw, ch = BW / z, BH / z
        dx = (BW - cw) / 2 * (0.6 * (u - 0.5) * (1 if idx % 2 == 0 else -1))
        cx, cy = (BW - cw) / 2 + dx, (BH - ch) / 2
        return im.crop((int(cx), int(cy), int(cx + cw), int(cy + ch))).resize((W, PHP), Image.BILINEAR)

    def word_time(words, key):
        k = B._norm(key.split()[0])
        return next((a for a, b, w in words if B._norm(w).startswith(k)), None)

    # ---------------------------------------------------------------- banners (broadcast style)
    _m = ImageDraw.Draw(Image.new("L", (1, 1)))
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

    def banner(s, size=96, maxw=860):
        """Tag (dark, yellow text) + one skewed bar per headline line: white, or green when it has [highlight]."""
        lines = [(ln.replace("[", "").replace("]", ""), "[" in ln) for ln in s["headline"]]
        f = font(B.F_BLACK_I, size)
        while f.size > 50 and max(_m.textlength(t, font=f) + 84 + 26 * i for i, (t, _) in enumerate(lines)) > maxw:
            f = font(B.F_BLACK_I, f.size - 2)
        tag = bar_img(s["tag"], font(B.F_XB_I, 34), (8, 22, 28), B.YELLOW, skew=16, padx=22, hpad=1.45)
        parts = [(tag, (0, 0))]
        y = tag.height - 34 + 8
        for i, (t, hl) in enumerate(lines):
            bi = bar_img(t, f, B.GREEN if hl else B.WHITE)
            parts.append((bi, (10 + 26 * i, y))); y += bi.height - 34 + 6
        return dict(parts=parts, h=y + 28, w=max(x + im.width for im, (x, _) in parts))

    def banner_flat(Bn):
        L = Image.new("RGBA", (Bn["w"], Bn["h"] + 34), (0, 0, 0, 0))
        for im, (x, y) in Bn["parts"]: L.alpha_composite(im, (x, y))
        return L

    def draw_banner(img, Bn, x0, y_bottom, u=None):
        """u=None: fully shown. Otherwise the tag and bars wipe in from the left one after the other."""
        y0 = y_bottom - Bn["h"]
        for i, (im, (x, y)) in enumerate(Bn["parts"]):
            r = 1.0 if u is None else B.ease((u - 0.10 - 0.09 * i) / 0.30)
            if r <= 0: continue
            piece = im if r >= 1 else im.crop((0, 0, max(1, int(im.width * r)), im.height))
            img.alpha_composite(piece, (int(x0 + x - 40 * (1 - r)), int(y0 + y)))

    # ---------------------------------------------------------------- news ticker
    def ticker_strip():
        items = cfg.get("ticker") or ([f"{st['tag']} — " + " ".join(ln.replace("[", "").replace("]", "") for ln in st["headline"])
                                       for st in stories] + ["kouponaki.com"])
        tf = font(B.F_XB_I, 32)
        seq = []
        for it in items: seq += [(it, B.WHITE), ("   •   ", B.YELLOW)]
        sw = int(sum(_m.textlength(t, font=tf) for t, _ in seq))
        im = Image.new("RGBA", (sw * 2 + 10, 58), (0, 0, 0, 0)); d = ImageDraw.Draw(im); x = 0
        for _ in range(2):
            for t, c in seq: d.text((x, 30), t, font=tf, fill=c, anchor="lm"); x += _m.textlength(t, font=tf)
        lab = bar_img(cfg.get("ticker_label", "ΠΑΣΑ στα ΝΕΑ"), font(B.F_BLACK_I, 34), B.GREEN, skew=14, padx=18, hpad=1.6)
        return dict(text=im, sw=sw, label=lab)

    TICK_Y = 1528
    def draw_ticker(img, T, tg):
        d = ImageDraw.Draw(img)
        d.rectangle((0, TICK_Y, W, TICK_Y + 58), fill=(6, 16, 20, 235))
        d.line([(0, TICK_Y), (W, TICK_Y)], fill=B.GREEN + (255,), width=3)
        off = int(tg * 115) % T["sw"]
        img.alpha_composite(T["text"].crop((off, 0, off + W, 58)), (0, TICK_Y))
        img.alpha_composite(T["label"], (-8, TICK_Y - 2))

    # ---------------------------------------------------------------- quote cards (who said what)
    def _col(c, default):
        if isinstance(c, str): return tuple(int(c.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4))
        return tuple(c) if c else default

    def quote_card(q, width=900):
        col = _col(q.get("color"), B.GREEN)
        nf, tf, sf = font(B.F_XB_I, 34), font(B.F_BLACK_I, 74), font(B.F_SEMI, 33)
        lines = B.wrap(q["text"], tf, width - 120)
        while len(lines) > 2 and tf.size > 46:
            tf = font(B.F_BLACK_I, tf.size - 4); lines = B.wrap(q["text"], tf, width - 120)
        sub = B.wrap(q["sub"], sf, width - 120) if q.get("sub") else []
        nw = int(_m.textlength(q["who"], font=nf)) + 46
        lh, sh_ = int(tf.size * 1.08), int(sf.size * 1.3)
        h = 24 + 50 + 16 + lh * len(lines) + ((10 + sh_ * len(sub)) if sub else 0) + 26
        im = Image.new("RGBA", (width + 40, h + 40), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
        d.rounded_rectangle((20, 20, 20 + width, 20 + h), 30, fill=(8, 22, 28, int(255 * float(q.get("opacity", 0.62)))))
        d.rounded_rectangle((20, 20, 36, 20 + h), 8, fill=col + (255,))
        d.rounded_rectangle((64, 44, 64 + nw, 44 + 50), 25, fill=col + (255,))
        d.text((64 + nw / 2, 44 + 26), q["who"], font=nf, fill=B.INK if sum(col) > 380 else B.WHITE, anchor="mm")
        y = 44 + 50 + 14
        for ln in lines:
            d.text((64, y), ln, font=tf, fill=B.WHITE, stroke_width=3, stroke_fill=B.INK); y += lh
        for ln in sub:
            d.text((64, y + 6), ln, font=sf, fill=(205, 220, 226), stroke_width=2, stroke_fill=B.INK); y += sh_
        return im

    # ---------------------------------------------------------------- stat badge
    def stat_card(value, label):
        f = font(B.F_BLACK_I, 118)
        m = ImageDraw.Draw(Image.new("L", (1, 1)))
        lf = font(B.F_XB_I, 32)
        w = int(max(m.textlength(value, font=f), m.textlength(label, font=lf))) + 70
        h = 200
        im = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((20, 30, 20 + w, 30 + h), 30, fill=(0, 0, 0, 160))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(12)))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((20, 20, 20 + w, 20 + h), 30, fill=(8, 22, 28, 240), outline=B.GREEN + (255,), width=5)
        d.text((20 + w / 2, 20 + 82), value, font=f, fill=B.YELLOW, anchor="mm")
        d.text((20 + w / 2, 20 + 162), label, font=lf, fill=B.WHITE, anchor="mm")
        return im

    # ---------------------------------------------------------------- captions
    cap_cache = {}
    def caption(img, chunk, t, ci, y=None):
        if not chunk: return
        act = next((i for i, (a, b, w) in enumerate(chunk) if a <= t < b + 0.08), -1)
        key = (ci, act)
        if key not in cap_cache:
            f = font(B.F_BLACK_I, 74)
            m = ImageDraw.Draw(Image.new("L", (1, 1)))
            words = [w for _, _, w in chunk]
            sp = m.textlength(" ", font=f) + 14          # room for the highlight box between words
            ws = [m.textlength(w, font=f) for w in words]
            tw = int(sum(ws) + sp * (len(ws) - 1)) + 60
            L = Image.new("RGBA", (tw, 130), (0, 0, 0, 0))
            S = Image.new("RGBA", L.size, (0, 0, 0, 0))
            d, sd = ImageDraw.Draw(L), ImageDraw.Draw(S)
            x = 30
            for i, w in enumerate(words):
                if i == act:
                    d.rounded_rectangle((x - 12, 22, x + ws[i] + 12, 112), 18, fill=B.GREEN + (255,))
                    d.text((x, 64), w, font=f, fill=B.INK, anchor="lm")
                else:
                    sd.text((x + 3, 70), w, font=f, fill=(0, 0, 0, 200), anchor="lm")
                    d.text((x, 64), w, font=f, fill=B.WHITE, anchor="lm", stroke_width=5, stroke_fill=B.INK)
                x += ws[i] + sp
            S = S.filter(ImageFilter.GaussianBlur(6)); S.alpha_composite(L)
            k = min(1.0, 800 / S.width)
            cap_cache[key] = S if k == 1 else S.resize((int(S.width * k), int(S.height * k)), Image.LANCZOS)
        L = cap_cache[key]
        p = B.ease_out_back(_clamp((t - chunk[0][0] + 0.06) / 0.18), 2.0)
        B.place(img, L, W / 2, y or CAP_Y, 0.8 + 0.2 * p, min(1, 0.35 + p))

    def cur_chunk(caps, t):
        for i, c in enumerate(caps):
            if c[0][0] - 0.06 <= t <= c[-1][1] + 0.2: return i, c
        return -1, None

    # ---------------------------------------------------------------- transitions
    def hblur(im, k):
        if k <= 1.05: return im
        w, h = im.size
        return im.resize((max(1, int(w / k)), h), Image.BILINEAR).resize((w, h), Image.BILINEAR)

    def push(old, new, p, y0):
        e = _inout(p); k = 1 + 14 * math.sin(math.pi * _clamp(p))
        canvas = new.copy()
        o, n = old.crop((0, y0, W, H)), new.crop((0, y0, W, H))
        xo, xn = -int(W * e), W - int(W * e)
        canvas.paste(hblur(o, k), (xo, y0)); canvas.paste(hblur(n, k), (xn, y0))
        d = ImageDraw.Draw(canvas)
        sk = 220
        d.polygon([(xn - 70, y0), (xn + 40, y0), (xn + 40 - sk, H), (xn - 70 - sk, H)], fill=B.GREEN + (255,))
        d.polygon([(xn + 40, y0), (xn + 58, y0), (xn + 58 - sk, H), (xn + 40 - sk, H)], fill=B.YELLOW + (255,))
        return canvas

    # ---------------------------------------------------------------- per-segment prep
    def prep_story(s, words):
        imgs = []
        if s.get("image"): imgs.append((0.0, load_photo(os.path.join(B.HERE, s["image"]), s.get("focus"), s.get("fit"))))
        for extra in s.get("images", []):
            ts = word_time(words, extra["at"]) if extra.get("at") else None
            if ts is not None: imgs.append((max(0.0, ts - 0.1), load_photo(os.path.join(B.HERE, extra["src"]), extra.get("focus"), extra.get("fit"))))
        imgs.sort(key=lambda x: x[0])
        layer = banner(s, size=int(s.get("banner_size", 92)))
        st = None
        if s.get("stat"):
            ts = word_time(words, s["stat"]["at"])
            if ts is not None: st = dict(t=ts, **s["stat"])
        qt = None
        if s.get("quote"):
            q = s["quote"]; tq = word_time(words, q["at"]) if q.get("at") else 0.3
            if tq is not None: qt = dict(t=tq, card=quote_card(q), hold=float(q.get("hold", 6.0)))
        hits = [tw for tw in (word_time(words, k) for k in s.get("punch_at", [])) if tw is not None]
        punch = [(ts, False) for ts, _ in imgs[1:]] + ([(st["t"], True)] if st else []) + [(tw, True) for tw in hits] + ([(qt["t"], True)] if qt else [])
        return dict(imgs=imgs, layer=layer, stat=st, punch=punch, hits=hits, quote=qt)

    def stat_frames(st):
        m = re.match(r"([\d.]+)(.*)", st["value"])
        if m and m.group(1).replace(".", "").isdigit():
            n, suf, dots = int(m.group(1).replace(".", "")), m.group(2), "." in m.group(1)
            vals = sorted(set(int(round(n * i / 24)) for i in range(25)))        # at most 25 steps for big numbers
            return [stat_card((f"{v:,}".replace(",", ".") if dots else str(v)) + suf, st["label"]) for v in vals]
        return [stat_card(st["value"], st["label"])]

    def story_frame(P, t, dur, tg, bu="t"):
        img = canvas0.copy()
        if bu == "t": bu = None if P.get("banner_shown") else t
        cur = max(i for i, (ts, _) in enumerate(P["imgs"]) if ts <= t) if P["imgs"] else -1
        if cur >= 0:
            ts, im = P["imgs"][cur]
            nxt = P["imgs"][cur + 1][0] if cur + 1 < len(P["imgs"]) else dur
            ph = kb_crop(im, _clamp((t - ts) / max(0.5, nxt - ts)), cur)
            if cur > 0 and t - ts < 0.25:
                ps, pim = P["imgs"][cur - 1]
                ph = Image.blend(kb_crop(pim, 1.0, cur - 1), ph, _clamp((t - ts) / 0.25))
            sc, fl = 1.0, 0.0                       # punch-in (+ short flash) on switches, numbers and key words
            for te, flash in P.get("punch", []):
                dt = t - te
                if 0 <= dt < 0.35: sc = max(sc, 1 + 0.06 * (1 - B.ease(dt / 0.35)))
                if flash and 0 <= dt < 0.16: fl = max(fl, 0.30 * (1 - dt / 0.16))
            if sc > 1.001:
                big = ph.resize((int(W * sc), int(PHP * sc)), Image.BILINEAR)
                ox, oy = (big.width - W) // 2, (big.height - PHP) // 2
                ph = big.crop((ox, oy, ox + W, oy + PHP))
            ph = ph.convert("RGBA")
            if fl > 0: ph.alpha_composite(Image.new("RGBA", (W, PHP), (255, 255, 255, int(255 * fl))))
            ph.alpha_composite(overlay)
            img.alpha_composite(ph, (0, PY))
        draw_banner(img, P["layer"], 30, CAP_Y - 70, bu)
        st = P["stat"]
        if st and st["t"] <= t < st["t"] + st.get("hold", 3.0):
            u = t - st["t"]
            fr = P["stat_fr"]
            card = fr[min(len(fr) - 1, int(len(fr) * _clamp(u / 0.55)))] if len(fr) > 1 else fr[0]
            a = 1 - _clamp((u - st.get("hold", 3.0) + 0.3) / 0.3)
            cx = (26 + card.width / 2) if st.get("side") == "left" else (925 - card.width / 2)   # keep faces clear
            B.place(img, card, cx, PY + 150, 0.6 + 0.4 * B.ease_out_back(u / 0.35, 2.2), a)
        qt = P.get("quote")
        if qt and qt["t"] <= t < qt["t"] + qt["hold"]:
            u = t - qt["t"]; c = qt["card"]
            a = 1 - _clamp((u - qt["hold"] + 0.3) / 0.3)
            B.place(img, c, c.width / 2 + 6, PY + 30 + c.height / 2, 0.88 + 0.12 * B.ease_out_back(u / 0.4, 2.0), min(1.0, u / 0.12) * a)
        return img

    def next_chip(text):
        lf, tf = font(B.F_XB_I, 29), font(B.F_BLACK_I, 38)
        lab = cfg.get("next_label", "ΕΠΟΜΕΝΟ")
        while tf.size > 24 and _m.textlength(text, font=tf) > 540: tf = font(B.F_BLACK_I, tf.size - 2)
        lw, tw, h = _m.textlength(lab, font=lf), _m.textlength(text, font=tf), 72
        w = int(8 + lw + 28 + 16 + 16 + 14 + tw + 26)
        im = Image.new("RGBA", (w + 30, h + 30), (0, 0, 0, 0))
        sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).rounded_rectangle((6, 10, w + 6, h + 10), h // 2, fill=(0, 0, 0, 140))
        im.alpha_composite(sh.filter(ImageFilter.GaussianBlur(8)))
        d = ImageDraw.Draw(im)
        d.rounded_rectangle((0, 0, w, h), h // 2, fill=(8, 22, 28, 238))
        d.rounded_rectangle((8, 8, 8 + lw + 28, h - 8), (h - 16) // 2, fill=B.YELLOW + (255,))
        d.text((8 + 14, h / 2 + 1), lab, font=lf, fill=B.INK, anchor="lm")
        x = 8 + lw + 28 + 16
        d.polygon([(x, h / 2 - 11), (x + 16, h / 2), (x, h / 2 + 11)], fill=B.GREEN + (255,))
        d.text((x + 30, h / 2 + 2), text, font=tf, fill=B.WHITE, anchor="lm")
        return im

    def cta_card(c):
        """End card question for the comments (on screen only: the voice never asks questions)."""
        parts = []
        t = bar_img(c.get("title", "ΓΡΑΨΕ ΣΤΑ ΣΧΟΛΙΑ"), font(B.F_XB_I, 40), (8, 22, 28), B.YELLOW, skew=16, padx=22, hpad=1.45)
        em = B.emoji_img("👇", 54)
        tt = Image.new("RGBA", (t.width + 60, max(t.height, em.height + 12)), (0, 0, 0, 0))
        tt.alpha_composite(t, (0, 0)); tt.alpha_composite(em, (t.width - 18, 2))
        parts.append((tt, (0, 0))); y = t.height - 34 + 26
        qf = font(B.F_BLACK_I, 86)
        for ln in B.wrap(c["question"], qf, 880):
            q = Image.new("RGBA", (int(_m.textlength(ln, font=qf)) + 30, int(qf.size * 1.25)), (0, 0, 0, 0))
            ImageDraw.Draw(q).text((6, 4), ln, font=qf, fill=B.WHITE, stroke_width=4, stroke_fill=B.INK)
            parts.append((q, (4, y))); y += int(qf.size * 1.05)
        y += 30
        for emo, label in c["options"]:
            blk = bar_img("    ", font(B.F_BLACK_I, 78), (8, 22, 28), skew=22, padx=30)
            e = B.emoji_img(emo, 74)
            blk.alpha_composite(e, ((blk.width - 30 - e.width) // 2 + 2, (blk.height - 34 - e.height) // 2))
            row = bar_img(label, font(B.F_BLACK_I, 74), B.WHITE, skew=22, padx=36)
            opt = Image.new("RGBA", (blk.width + row.width, max(blk.height, row.height)), (0, 0, 0, 0))
            opt.alpha_composite(blk, (0, 0)); opt.alpha_composite(row, (blk.width - 40, (blk.height - row.height) // 2))
            parts.append((opt, (10, y))); y += blk.height - 34 + 22
        return dict(parts=parts, h=y + 28, w=max(x + im.width for im, (x, _) in parts))

    def end_card():
        L = bg_plain.copy()
        t = bar_img(cfg.get("end_title", "ΣΗΜΕΡΑ ΕΙΔΑΜΕ"), font(B.F_XB_I, 40), (8, 22, 28), B.YELLOW, skew=16, padx=22, hpad=1.45)
        L.alpha_composite(t, (40, PROG_Y + 46))
        y = PROG_Y + 46 + t.height
        for i, s in enumerate(stories, 1):
            num = bar_img(str(i), font(B.F_BLACK_I, 76), B.GREEN, skew=20, padx=22)
            text = " ".join(ln.replace("[", "").replace("]", "") for ln in s["headline"])
            f = font(B.F_BLACK_I, 66)
            while f.size > 34 and _m.textlength(text, font=f) + 84 > 880 - num.width: f = font(B.F_BLACK_I, f.size - 2)
            row = bar_img(text, f, B.WHITE, skew=20)
            L.alpha_composite(num, (40, y)); L.alpha_composite(row, (40 + num.width - 30, y + (num.height - row.height) // 2))
            y += num.height + 10
        return L

    # ---------------------------------------------------------------- render
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow",
                             "-crf", str(cfg.get("crf", 16)), "-profile:v", "high", "-g", str(FPS * 2),
                             "-pix_fmt", "yuv420p", video], stdin=subprocess.PIPE)
    FCARD = B.follow_card(cfg) if FT else None
    TK = ticker_strip()
    T0 = 0.0
    last = None
    k_story = -1
    cover_saved = False
    P_pre = None          # story 1 prepared during the intro sting
    hook_first = None     # first frame, for the seamless loop at the end
    LOOP = float(cfg.get("loop_push", 0.4)) if cfg.get("hook") else 0.0
    for si, ((kind, s), (wav, words, dur, lead)) in enumerate(zip(segments, audio)):
        n = int(round(dur * FPS))
        caps = B.chunks(words, s["voice"], maxw=3)
        ev = []
        if kind == "hook":
            bg = B.hook_background(os.path.join(B.HERE, s["image"]) if s.get("image") else None, s.get("focus"), s.get("blur", 0))
            layer = banner_flat(banner(s, size=min(124, int(s.get("size", 124))), maxw=880))
            SB = B.scoreboard_card(s["scoreboard"]) if s.get("scoreboard") else None
            HP = [tw for tw in (word_time(words, k) for k in s.get("punch_at", [])) if tw is not None]
            QC = [quote_card(q, width=940) for q in s.get("quotes", [])]
            QT = [0.1] + [(word_time(words, q["at"]) if q.get("at") else 0.1 + 1.4 * i) or 1.5 for i, q in list(enumerate(s.get("quotes", [])))[1:]]
            QT = QT[:len(QC)]
            for tq in QT[1:]: ev.append((tq, "hit", 0.4))
            cover_at = max([0.6] + [tq + 0.55 for tq in QT])
            if QC: ev.append((QT[0], "pop", 0.35))
            for f in range(n):
                t = f / FPS
                img = B.hook_frame(bg, t, dur)
                pulse = max([1.0] + [1 + 0.07 * (1 - B.ease((t - tw) / 0.35)) for tw in HP if 0 <= t - tw < 0.35])
                img.alpha_composite(logo_s, (46, HEAD_Y + 10))
                if badge: img.alpha_composite(badge, (930 - badge.width, HEAD_Y - 6))
                punch = 1.0 + 0.07 * (1 - B.ease(t / 0.25))
                shake = int(9 * math.sin(t * 60) * max(0, 1 - t / 0.35))
                if SB is not None:
                    B.place(img, SB, W / 2 + shake, 560, ((1 + 0.6 * (punch - 1)) * 0.94 + 0.03 * t / dur) * pulse)
                if QC:
                    gap = 22; tot = sum(c.height - 40 for c in QC) + gap * (len(QC) - 1); y0 = 545 - tot / 2
                    for i, (c, tq) in enumerate(zip(QC, QT)):
                        u = t - tq
                        if u > 0:
                            e = B.ease_out_back(u / 0.4, 2.0); a = min(1.0, u / 0.1)
                            side = -1 if i % 2 == 0 else 1
                            B.place(img, c, W / 2 + side * 34 * (1 - B.ease(u / 0.4)), y0 + (c.height - 40) / 2 + 20, 0.9 + 0.1 * e, a)
                        y0 += c.height - 40 + gap
                L = layer if punch == 1.0 else layer.resize((int(layer.width * punch), int(layer.height * punch)), Image.BILINEAR)
                img.alpha_composite(L, (34 + shake - (L.width - layer.width) // 2, (850 if (SB is not None or QC) else 760) - (L.height - layer.height) // 2))
                draw_ticker(img, TK, T0 + t)
                if not cover_saved and t >= (cover_at if QC else 0.6):   # cover for the profile grid: no caption on it
                    img.convert("RGB").save(os.path.splitext(out)[0] + "-cover.jpg", quality=95); cover_saved = True
                ci, ch = cur_chunk(caps, t); caption(img, ch, t, (si, ci), 1350)
                if f == 0: hook_first = img.copy()
                proc.stdin.write(img.tobytes()); last = img
            for tw in HP: ev.append((tw, "hit", 0.35))
        elif kind == "intro" and intro_video:
            sting = float(s.get("sting") or 0)
            nxt = segments[si + 1] if si + 1 < len(segments) else None
            use_sting = sting > 0 and nxt is not None and nxt[0] == "story"
            clip_t = min(dur, sting + 0.2) if use_sting else dur
            dec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-ss", f"{intro_start:.3f}", "-i", intro_video, "-t", f"{clip_t:.3f}",
                                    "-vf", f"scale={W}:{H},fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgba", "-"], stdout=subprocess.PIPE)
            if use_sting:
                P_pre = prep_story(nxt[1], audio[si + 1][1]); P_pre["banner_shown"] = True
            fr_last = clip_last = None
            for f in range(n):
                t = f / FPS
                if not use_sting or t < sting:
                    buf = dec.stdout.read(W * H * 4)
                    if len(buf) == W * H * 4: fr_last = Image.frombytes("RGBA", (W, H), buf)
                    img = fr_last.copy()
                    if t < 0.14:                                    # green flash on the cut from the hook
                        img.alpha_composite(Image.new("RGBA", (W, H), B.GREEN + (int(150 * (1 - t / 0.14)),)))
                    clip_last = img
                else:                                               # story 1 slides in under the intro line
                    u = t - sting
                    content = story_frame(P_pre, 0.0, audio[si + 1][2], T0 + t, bu=u - 0.05)
                    draw_ticker(content, TK, T0 + t)
                    img = content.copy(); header(img); progress(img, 0, 0.0)
                    if u < TR: img = push(clip_last, img, u / TR, 0)
                ci, ch = cur_chunk(caps, t); caption(img, ch, t, (si, ci))
                proc.stdin.write(img.tobytes()); last = img
            dec.stdout.read(); dec.stdout.close(); dec.wait()
            ev.append((0.0, "whoosh", 0.4))
            if use_sting: ev.append((sting, "whoosh", 0.38))
        elif kind == "story":
            k_story += 1
            pre_shown = P_pre is not None and k_story == 0
            P = P_pre if pre_shown else prep_story(s, words)
            if P["stat"]:
                P["stat_fr"] = stat_frames(P["stat"]); ev.append((P["stat"]["t"], "pop", 0.45))
            for ts, _ in P["imgs"][1:]: ev.append((ts, "whoosh", 0.18))
            for tw in P["hits"]: ev.append((tw, "hit", 0.32))
            if not pre_shown: ev.append((0.0, "whoosh", 0.38))
            from_intro = segments[si - 1][0] in ("intro", "hook")
            chip = None
            if k_story + 1 < NS and cfg.get("next_chip", True):
                chip = next_chip(stories[k_story + 1]["tag"]); cs = max(2.0, dur - 1.75)
                st = P["stat"]   # keep clear of a number card on the same side
                busy_left = bool(st and st.get("side") == "left" and st["t"] < dur and st["t"] + st.get("hold", 3.0) > cs)
                chip_left = not busy_left
                ev.append((cs, "click", 0.3))
            for f in range(n):
                t = f / FPS
                content = story_frame(P, t, dur, T0 + t)
                if chip is not None and t >= cs:
                    q = B.ease((t - cs) / 0.3)
                    x = 26 - (chip.width + 40) * (1 - q) if chip_left else 925 - chip.width + 30 + (chip.width + 60) * (1 - q)
                    content.alpha_composite(chip, (int(x), PY + 18))
                draw_ticker(content, TK, T0 + t)
                ci, ch = cur_chunk(caps, t); caption(content, ch, t, (si, ci))
                clean = content                      # header-free copy for the next push
                frac = _clamp(t / dur)
                if last is not None and t < TR and not pre_shown:
                    if from_intro:                   # the header arrives with the first story
                        img = content.copy(); header(img); progress(img, k_story, frac)
                        img = push(last, img, t / TR, 0)
                    else:                            # header stays put, only the content moves
                        img = push(last, content, t / TR, 0); header(img); progress(img, k_story, frac)
                else:
                    img = content.copy(); header(img); progress(img, k_story, frac)
                proc.stdin.write(img.tobytes())
            last = clean
        else:  # recap / end card
            CTA = cta_card(cfg["comment_cta"]) if cfg.get("comment_cta") else None
            EC = bg_plain.copy() if CTA else end_card()
            cta_bottom = PROG_Y + 40 + (CTA["h"] if CTA else 0)
            fy = int(cfg.get("follow", {}).get("y", max(1150, cta_bottom + 175) if CTA else 1150))
            ev.append((0.0, "whoosh", 0.38))
            if LOOP and hook_first is not None: ev.append((dur - LOOP, "whoosh", 0.35))
            for f in range(n):
                t = f / FPS
                content = EC.copy()
                if CTA: draw_banner(content, CTA, 40, cta_bottom, t - 0.15)
                draw_ticker(content, TK, T0 + t)
                if not FT or t < FT["tF"]:
                    ci, ch = cur_chunk(caps, t); caption(content, ch, t, (si, ci))
                img = push(last, content, t / TR, 0) if (last is not None and t < TR) else content
                header(img); progress(img, NS, 1.0)
                if FT: B.draw_follow(img, t, FCARD, FT, CY=fy, dim=not CTA)
                if LOOP and hook_first is not None and t >= dur - LOOP:     # last frames slide into the first one
                    img = push(img, hook_first, (t - (dur - LOOP)) / LOOP, 0)
                proc.stdin.write(img.tobytes())
            last = img
        if ev: sfx[si] = ev
        T0 += dur
    proc.stdin.close(); proc.wait()
    return sfx

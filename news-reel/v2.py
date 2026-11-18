"""«ΠΑΣΑ στα ΝΕΑ» v2 look (script.json: "layout": "v2").

What changes against the original renderer in build.py:
- Safe-zone layout: nothing important under the Instagram/TikTok UI (top bar, right icons, bottom caption).
  Compact header (logotype + date + small kouponaki logo) at y≈222, captions at y≈1290.
- Progress bar (one segment per story) under the header.
- Push transitions with motion blur and a green wipe band (no empty frames), whoosh on every change.
- Photos: colour grade + vignette, Ken Burns that alternates direction, several photos per story
  ("images": [{"src", "at"}] switch when the voice says the word "at").
- Stat callouts ("stat": {"value", "label", "at"}): badge that pops (count-up for numbers) with a pop sound.
- Captions: 2–3 words that pop in, active word on a green highlight.
- Clean end card (numbered headlines) under the follow pop-up; cover image for the profile grid.
"""
import math, os, re, subprocess
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

HEAD_Y, PH, CAP_Y, TR = 222, 700, 1360, 0.32


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
        img = Image.composite(Image.new("RGB", (W, H), (40, 70, 75)), img, n)
        d = ImageDraw.Draw(img, "RGBA")
        for i in range(3):                                   # one quiet stripe group, top-left
            ox = -60 + i * 44
            d.polygon([(ox, 0), (ox + 24, 0), (ox - 176, 200), (ox - 200, 200)], fill=B.GREEN + (90,))
        return img.convert("RGBA")

    title = B.title_layer(rnd); title = title.resize((430, int(title.height * 430 / title.width)), Image.LANCZOS)
    badge = B.date_badge(B.reel_date(cfg), w=78, h=96) if cfg.get("show_date", True) else None
    lg = Image.open(os.path.join(B.HERE, cfg.get("logo", "assets/logo.png"))).convert("RGBA")
    logo_s = lg.resize((300, int(lg.height * 300 / lg.width)), Image.LANCZOS)
    TH = title.height
    PROG_Y = HEAD_Y + TH + 12
    PY = PROG_Y + 24
    base = background()
    base.alpha_composite(title, (46, HEAD_Y))
    if badge: base.alpha_composite(badge, (46 + title.width + 6, HEAD_Y + (TH - badge.height) // 2))
    base.alpha_composite(logo_s, (1024 - logo_s.width, HEAD_Y + (TH - logo_s.height) // 2))

    stories = [s for k, s in segments if k == "story"]
    NS = len(stories)

    def progress(img, k, frac):
        d = ImageDraw.Draw(img)
        x0, x1, gap = 46, 1024, 12
        w = (x1 - x0 - gap * (NS - 1)) / max(1, NS)
        for i in range(NS):
            a = x0 + i * (w + gap)
            d.rounded_rectangle((a, PROG_Y, a + w, PROG_Y + 8), 4, fill=(255, 255, 255, 55))
            f = 1.0 if i < k else (frac if i == k else 0.0)
            if f > 0: d.rounded_rectangle((a, PROG_Y, a + max(8, w * f), PROG_Y + 8), 4, fill=B.GREEN + (255,))

    # ---------------------------------------------------------------- photos
    def grade(im):
        im = ImageEnhance.Contrast(im).enhance(1.08)
        im = ImageEnhance.Color(im).enhance(1.12)
        return im.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))

    BW, BH = int(W * 1.14), int(PH * 1.14)
    def load_photo(path):
        im = Image.open(path).convert("RGB")
        k = max(BW / im.width, BH / im.height)
        im = im.resize((int(im.width * k) + 1, int(im.height * k) + 1), Image.LANCZOS)
        l, t = (im.width - BW) // 2, (im.height - BH) // 2
        return grade(im.crop((l, t, l + BW, t + BH)))

    overlay = Image.new("RGBA", (W, PH), (0, 0, 0, 0)); od = ImageDraw.Draw(overlay)
    for y in range(PH):
        a = int(200 * ((y - (PH - 240)) / 240) ** 1.6) if y > PH - 240 else 0
        od.line([(0, y), (W, y)], fill=B.BG2 + (a,))
    vig = Image.new("L", (W, PH), 0); vd = ImageDraw.Draw(vig)
    for i in range(60):                                       # soft side vignette
        vd.rectangle((i, 0, W - 1 - i, PH), outline=int(110 * (1 - i / 60) ** 2))
    overlay.alpha_composite(Image.merge("RGBA", (Image.new("L", (W, PH), 0),) * 3 + (vig,)))

    def kb_crop(im, u, idx):
        """Ken Burns: zoom in on even photos, out on odd ones, with a slight pan."""
        z = 1.0 + 0.10 * (u if idx % 2 == 0 else 1 - u)
        cw, ch = BW / z, BH / z
        dx = (BW - cw) / 2 * (0.6 * (u - 0.5) * (1 if idx % 2 == 0 else -1))
        cx, cy = (BW - cw) / 2 + dx, (BH - ch) / 2
        return im.crop((int(cx), int(cy), int(cx + cw), int(cy + ch))).resize((W, PH), Image.BILINEAR)

    def word_time(words, key):
        k = B._norm(key.split()[0])
        return next((a for a, b, w in words if B._norm(w).startswith(k)), None)

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
            sp = m.textlength(" ", font=f)
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
        if s.get("image"): imgs.append((0.0, load_photo(os.path.join(B.HERE, s["image"]))))
        for extra in s.get("images", []):
            ts = word_time(words, extra["at"]) if extra.get("at") else None
            if ts is not None: imgs.append((max(0.0, ts - 0.1), load_photo(os.path.join(B.HERE, extra["src"]))))
        imgs.sort(key=lambda x: x[0])
        layer = B.story_layer(s, rnd, body=False, size=100)
        layer = layer.resize((int(layer.width * 0.86), int(layer.height * 0.86)), Image.LANCZOS)
        st = None
        if s.get("stat"):
            ts = word_time(words, s["stat"]["at"])
            if ts is not None: st = dict(t=ts, **s["stat"])
        return dict(imgs=imgs, layer=layer, stat=st)

    def stat_frames(st):
        m = re.match(r"(\d+)(.*)", st["value"])
        if m:
            n, suf = int(m.group(1)), m.group(2)
            return [stat_card(f"{v}{suf}", st["label"]) for v in range(n + 1)]
        return [stat_card(st["value"], st["label"])]

    def story_frame(P, t, dur, k):
        img = base.copy()
        progress(img, k, _clamp(t / dur))
        # photo (crossfade on switches)
        cur = max(i for i, (ts, _) in enumerate(P["imgs"]) if ts <= t) if P["imgs"] else -1
        if cur >= 0:
            ts, im = P["imgs"][cur]
            nxt = P["imgs"][cur + 1][0] if cur + 1 < len(P["imgs"]) else dur
            ph = kb_crop(im, _clamp((t - ts) / max(0.5, nxt - ts)), cur)
            if cur > 0 and t - ts < 0.25:
                ps, pim = P["imgs"][cur - 1]
                prev = kb_crop(pim, 1.0, cur - 1)
                ph = Image.blend(prev, ph, _clamp((t - ts) / 0.25))
            ph = ph.convert("RGBA"); ph.alpha_composite(overlay)
            img.alpha_composite(ph, (0, PY))
        img.alpha_composite(P["layer"], (26, PY + PH - 132))
        st = P["stat"]
        if st and st["t"] <= t < st["t"] + st.get("hold", 3.0):
            u = t - st["t"]
            fr = P["stat_fr"]
            card = fr[min(len(fr) - 1, int(len(fr) * _clamp(u / 0.55)))] if len(fr) > 1 else fr[0]
            a = 1 - _clamp((u - st.get("hold", 3.0) + 0.3) / 0.3)
            B.place(img, card, 905 - card.width / 2 + 20, PY + 150, 0.6 + 0.4 * B.ease_out_back(u / 0.35, 2.2), a)
        return img

    def end_card():
        L = base.copy()
        d = ImageDraw.Draw(L)
        d.text((60, PY + 18), cfg.get("end_title", "ΣΗΜΕΡΑ ΕΙΔΑΜΕ"), font=font(B.F_XB_I, 46), fill=B.YELLOW)
        y = PY + 96
        for i, s in enumerate(stories, 1):
            d.rounded_rectangle((46, y, 930, y + 150), 26, fill=(8, 22, 28, 225), outline=(255, 255, 255, 30), width=2)
            d.ellipse((72, y + 33, 156, y + 117), fill=B.GREEN + (255,))
            d.text((114, y + 77), str(i), font=font(B.F_BLACK_I, 58), fill=B.INK, anchor="mm")
            hf = font(B.F_BLACK_I, 54)
            lines = s["headline"]
            while hf.size > 34 and max(B.rich_len(d, ln, hf) for ln in lines) > 720: hf = font(B.F_BLACK_I, hf.size - 2)
            lh = int(hf.size * 1.02); yy = y + 75 - lh * len(lines) / 2
            for ln in lines:
                B.rich(d, (186, yy), ln, hf, B.WHITE, B.YELLOW); yy += lh
            y += 172
        return L

    # ---------------------------------------------------------------- render
    proc = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba",
                             "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "slow",
                             "-crf", str(cfg.get("crf", 16)), "-profile:v", "high", "-g", str(FPS * 2),
                             "-pix_fmt", "yuv420p", video], stdin=subprocess.PIPE)
    FCARD = B.follow_card(cfg) if FT else None
    last = None
    k_story = -1
    cover_saved = False
    for si, ((kind, s), (wav, words, dur, lead)) in enumerate(zip(segments, audio)):
        n = int(round(dur * FPS))
        caps = B.chunks(words, s["voice"], maxw=3)
        ev = []
        if kind == "hook":
            bg = B.hook_background(os.path.join(B.HERE, s["image"]) if s.get("image") else None, s.get("focus"), s.get("blur", 0))
            layer = B.story_layer(s, rnd, body=False, size=min(150, int(s.get("size", 150))))
            layer = layer.resize((int(layer.width * 0.9), int(layer.height * 0.9)), Image.LANCZOS)
            SB = B.scoreboard_card(s["scoreboard"]) if s.get("scoreboard") else None
            for f in range(n):
                t = f / FPS
                img = B.hook_frame(bg, t, dur)
                img.alpha_composite(logo_s, (46, HEAD_Y + 10))
                if badge: img.alpha_composite(badge, (930 - badge.width, HEAD_Y - 6))
                punch = 1.0 + 0.07 * (1 - B.ease(t / 0.25))
                shake = int(9 * math.sin(t * 60) * max(0, 1 - t / 0.35))
                if SB is not None:
                    B.place(img, SB, W / 2 + shake, 560, (1 + 0.6 * (punch - 1)) * 0.94 + 0.03 * t / dur)
                L = layer if punch == 1.0 else layer.resize((int(layer.width * punch), int(layer.height * punch)), Image.BILINEAR)
                img.alpha_composite(L, (26 + shake - (L.width - layer.width) // 2, (830 if SB is not None else 760) - (L.height - layer.height) // 2))
                if not cover_saved and t >= 0.6:   # cover for the profile grid: no caption on it
                    img.convert("RGB").save(os.path.splitext(out)[0] + "-cover.jpg", quality=95); cover_saved = True
                ci, ch = cur_chunk(caps, t); caption(img, ch, t, (si, ci), 1350)
                proc.stdin.write(img.tobytes()); last = img
        elif kind == "intro" and intro_video:
            dec = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-ss", f"{intro_start:.3f}", "-i", intro_video, "-t", f"{dur:.3f}",
                                    "-vf", f"scale={W}:{H},fps={FPS}", "-f", "rawvideo", "-pix_fmt", "rgba", "-"], stdout=subprocess.PIPE)
            fr_last = None
            for f in range(n):
                buf = dec.stdout.read(W * H * 4)
                if len(buf) == W * H * 4: fr_last = Image.frombytes("RGBA", (W, H), buf)
                img = fr_last.copy(); t = f / FPS
                if t < 0.14:                                    # green flash on the cut from the hook
                    img.alpha_composite(Image.new("RGBA", (W, H), B.GREEN + (int(150 * (1 - t / 0.14)),)))
                ci, ch = cur_chunk(caps, t); caption(img, ch, t, (si, ci))
                proc.stdin.write(img.tobytes()); last = img
            dec.stdout.close(); dec.wait()
            ev.append((0.0, "whoosh", 0.4))
        elif kind == "story":
            k_story += 1
            P = prep_story(s, words)
            if P["stat"]:
                P["stat_fr"] = stat_frames(P["stat"]); ev.append((P["stat"]["t"], "pop", 0.45))
            for ts, _ in P["imgs"][1:]: ev.append((ts, "whoosh", 0.18))
            ev.append((0.0, "whoosh", 0.38))
            y0 = 0 if segments[si - 1][0] in ("intro", "hook") else PROG_Y - 6
            for f in range(n):
                t = f / FPS
                img = story_frame(P, t, dur, k_story)
                ci, ch = cur_chunk(caps, t); caption(img, ch, t, (si, ci))
                if last is not None and t < TR: img = push(last, img, t / TR, y0)
                proc.stdin.write(img.tobytes())
            last = img
        else:  # recap / end card
            EC = end_card(); progress(EC, NS, 1.0)
            ev.append((0.0, "whoosh", 0.38))
            for f in range(n):
                t = f / FPS
                img = EC.copy()
                if FT: B.draw_follow(img, t, FCARD, FT, CY=int(cfg.get("follow", {}).get("y", 860)))
                if not FT or t < FT["tF"]:
                    ci, ch = cur_chunk(caps, t); caption(img, ch, t, (si, ci))
                if last is not None and t < TR: img = push(last, img, t / TR, PROG_Y - 6)
                proc.stdin.write(img.tobytes())
            last = img
        if ev: sfx[si] = ev
    proc.stdin.close(); proc.wait()
    return sfx

"""
Nexos Market - Reel "pro": animado cuadro por cuadro (30 fps, 1080x1920).

Escenas:
  1. Gancho (2 s): 3 productos que entran con efecto pop + título.
  2. Un producto cada ~1,7 s: foto con zoom suave, entrada deslizando, nombre que sube,
     precio que "salta" y sticker de descuento. Barra de progreso arriba (estilo historias).
  3. Cierre (3,2 s): grilla de productos de la tienda + "+N productos en la web · link en la bio".
Música: tema de .github/nexos/musica (Pixabay) con fade.
"""
import math
import os
import subprocess
import time

from PIL import Image, ImageDraw, ImageFilter

import generar_ofertas as go

W, H, FPS = 1080, 1920, 30
T_HOOK, T_PROD, T_OUT = 2.0, 1.7, 3.4
SLIDE = 0.28


def ease_out(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def ease_back(t):           # rebote suave al final
    t = max(0.0, min(1.0, t))
    c = 1.70158
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def fondo():
    bg = Image.new("RGB", (W, H), go.BG)
    g = Image.new("RGB", (W, H), go.BG)
    d = ImageDraw.Draw(g)
    d.ellipse((-200, 200, 900, 1300), fill=(40, 70, 190))
    d.ellipse((300, 900, 1300, 2000), fill=(150, 20, 110))
    return Image.blend(bg, g.filter(ImageFilter.GaussianBlur(220)), 0.55)


def centrado(d, y, txt, fnt, color, maxw=W - 120):
    while d.textlength(txt, font=fnt) > maxw and fnt.size > 28:
        fnt = fnt.font_variant(size=fnt.size - 4)
    d.text(((W - d.textlength(txt, font=fnt)) / 2, y), txt, font=fnt, fill=color)


def tarjeta(foto, w, h, radio=48):
    c = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ImageDraw.Draw(c).rounded_rectangle((0, 0, w - 1, h - 1), radius=radio, fill=(255, 255, 255, 255))
    if foto is not None:
        ph = go.encajar(foto, w - 70, h - 70).convert("RGBA")
        c.alpha_composite(ph, ((w - ph.width) // 2, (h - ph.height) // 2))
    return c


def pegar_escalado(base, img, cx, cy, s, alpha=1.0):
    if s <= 0.02 or alpha <= 0.01:
        return
    w, h = max(1, int(img.width * s)), max(1, int(img.height * s))
    im = img.resize((w, h), Image.BILINEAR)
    if alpha < 1:
        a = im.split()[3].point(lambda v: int(v * alpha))
        im.putalpha(a)
    base.alpha_composite(im, (int(cx - w / 2), int(cy - h / 2)))


class Reel:
    def __init__(self, items, fotos, titulo, subtitulo, total, grid_fotos):
        self.items, self.fotos = items, fotos
        self.titulo, self.subtitulo, self.total = titulo, subtitulo, total
        self.grid = [f for f in grid_fotos if f is not None][:9]
        self.bg = fondo().convert("RGBA")
        self.marca = Image.new("RGBA", (W, 140), (0, 0, 0, 0))
        go.marca(self.marca, ImageDraw.Draw(self.marca), 30, x=(W - 330) // 2)
        self.cards = [tarjeta(f, 900, 900) for f in fotos]
        self.mini = [tarjeta(f, 300, 300, 30) for f in self.grid]
        self.n = len(items)
        self.dur = T_HOOK + self.n * T_PROD + T_OUT

    # --- escenas -------------------------------------------------------
    def hook(self, t):
        im = self.bg.copy()
        im.alpha_composite(self.marca, (0, 110))
        pos = [(300, 760, -10), (780, 760, 10), (540, 690, 0)]
        for k, (cx, cy, ang) in enumerate(pos):
            if k >= len(self.cards):
                continue
            s = ease_back((t - 0.12 * k) / 0.45) * (0.42 if k < 2 else 0.55)
            card = self.cards[[1, 2, 0][k] if len(self.cards) > 2 else k].rotate(ang, expand=True, resample=Image.BICUBIC)
            pegar_escalado(im, card, cx, cy, s)
        d = ImageDraw.Draw(im, 'RGBA')
        a = ease_out((t - 0.55) / 0.4)
        y = 1200 + (1 - a) * 60
        if a > 0:
            centrado(d, y, self.titulo, go.font("Black", 120), (255, 255, 255))
            centrado(d, y + 150, self.subtitulo, go.font("Black", 72), go.CYAN)
        b = ease_out((t - 0.95) / 0.35)
        if b > 0:
            pill = "Precios del " + time.strftime("%d/%m")
            fp = go.font("Bold", 46)
            pw = d.textlength(pill, font=fp) + 70
            d.rounded_rectangle(((W - pw) / 2, 1460, (W + pw) / 2, 1550), radius=45, fill=go.GREEN)
            centrado(d, 1478, pill, fp, (255, 255, 255))
        return im

    def producto(self, i, t):
        im = self.bg.copy()
        im.alpha_composite(self.marca, (0, 110))
        d = ImageDraw.Draw(im, 'RGBA')
        p = self.items[i]
        # contador
        cnt = f"{i + 1}/{self.n}"
        fc = go.font("Bold", 36)
        d.rounded_rectangle((W - 60 - d.textlength(cnt, font=fc) - 40, 140, W - 60, 200), radius=30, fill=(45, 52, 66))
        d.text((W - 80 - d.textlength(cnt, font=fc), 150), cnt, font=fc, fill=(255, 255, 255))
        # tarjeta con zoom y entrada deslizando
        sl = ease_out(t / SLIDE)
        cx = 540 + (1 - sl) * 900
        zoom = 1.0 + 0.06 * (t / T_PROD)
        card = self.cards[i]
        inner = card.copy()
        if zoom > 1:
            w2, h2 = int(card.width * zoom), int(card.height * zoom)
            z = card.resize((w2, h2), Image.BILINEAR)
            off = ((w2 - card.width) // 2, (h2 - card.height) // 2)
            z = z.crop((off[0], off[1], off[0] + card.width, off[1] + card.height))
            mask = Image.new("L", card.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, card.width - 1, card.height - 1), radius=48, fill=255)
            inner = Image.new("RGBA", card.size, (0, 0, 0, 0))
            inner.paste(z, (0, 0), mask)
        im.alpha_composite(inner, (int(cx - 450), 270))
        # sticker de descuento
        pc = go.pct(p)
        if pc:
            s = ease_back((t - 0.30) / 0.35)
            st = Image.new("RGBA", (300, 150), (0, 0, 0, 0))
            sd = ImageDraw.Draw(st)
            sd.rounded_rectangle((0, 0, 299, 149), radius=40, fill=go.GREEN)
            fb = go.font("Black", 84)
            tx = f"-{pc}%"
            sd.text(((300 - sd.textlength(tx, font=fb)) / 2, 22), tx, font=fb, fill=(255, 255, 255))
            pegar_escalado(im, st.rotate(-8, expand=True, resample=Image.BICUBIC), cx + 300, 330, s)
        d = ImageDraw.Draw(im, 'RGBA')
        # nombre
        a = ease_out((t - 0.12) / 0.35)
        if a > 0:
            fn = go.font("Bold", 50)
            y = 1215 + (1 - a) * 50
            for ln in go.wrap(d, p.get("name"), fn, W - 140, 2):
                d.text((70, y), ln, font=fn, fill=(255, 255, 255))
                y += 62
        # precio (salta)
        s = ease_back((t - 0.30) / 0.40)
        if s > 0:
            txt = go.money(p.get("price"))
            pi = Image.new("RGBA", (900, 170), (0, 0, 0, 0))
            pd = ImageDraw.Draw(pi)
            fpz = go.font("Black", 130)
            pd.text((0, 0), txt, font=fpz, fill=(255, 255, 255))
            bb = pi.getbbox() or (0, 0, 10, 10)
            pi = pi.crop(bb)
            pegar_escalado(im, pi, 70 + pi.width / 2, 1440 + pi.height / 2, s)
            if pc:
                fa = go.font("Medium", 40)
                ta = "Antes " + go.money(p.get("prev_price"))
                d.text((74, 1372), ta, font=fa, fill=go.MUTED)
                tw = d.textlength(ta, font=fa)
                d.line((74, 1397, 74 + tw, 1397), fill=go.MUTED, width=3)
        # botón
        b = ease_out((t - 0.5) / 0.3)
        if b > 0:
            y = 1660 + (1 - b) * 40
            d.rounded_rectangle((70, y, W - 70, y + 100), radius=50, fill=go.BLUE)
            centrado(d, y + 26, "Mirá todo en la web", go.font("Bold", 42), (255, 255, 255))
        return im

    def cierre(self, t):
        im = self.bg.copy()
        im.alpha_composite(self.marca, (0, 110))
        d = ImageDraw.Draw(im, 'RGBA')
        a = ease_out(t / 0.4)
        centrado(d, 260 + (1 - a) * 40, f"Y +{self.total} productos", go.font("Black", 104), (255, 255, 255))
        centrado(d, 400 + (1 - a) * 40, "más en la web", go.font("Black", 84), go.CYAN)
        # grilla 3x3 (estilo tienda)
        for k, m in enumerate(self.mini):
            r, c = divmod(k, 3)
            cx, cy = 250 + c * 290, 640 + r * 285
            s = ease_back((t - 0.25 - 0.06 * k) / 0.35)
            pegar_escalado(im, m, cx, cy, s * 0.88)
        d = ImageDraw.Draw(im, 'RGBA')
        b = ease_out((t - 0.9) / 0.4)
        if b > 0:
            # barra tipo navegador
            y = 1390 + (1 - b) * 40
            d.rounded_rectangle((110, y, W - 110, y + 96), radius=48, fill=(255, 255, 255))
            centrado(d, y + 24, "market.nexosmaps.com", go.font("Bold", 46), (17, 24, 39))
            pul = 1 + 0.05 * math.sin(max(0, t - 1.3) * 8)
            bt = Image.new("RGBA", (760, 120), (0, 0, 0, 0))
            bd = ImageDraw.Draw(bt)
            bd.rounded_rectangle((0, 0, 759, 119), radius=60, fill=go.GREEN)
            ft = go.font("Black", 54)
            bd.text(((760 - bd.textlength("Link en la bio", font=ft)) / 2, 28), "Link en la bio", font=ft, fill=(255, 255, 255))
            pegar_escalado(im, bt, 540, 1600, pul * b)
            d = ImageDraw.Draw(im, 'RGBA')
            centrado(d, 1700, "Seguinos: @nexos.marketofertas", go.font("Bold", 40), go.MUTED)
        return im

    def frame(self, t):
        if t < T_HOOK:
            im = self.hook(t)
        elif t < T_HOOK + self.n * T_PROD:
            i = int((t - T_HOOK) // T_PROD)
            im = self.producto(i, t - T_HOOK - i * T_PROD)
        else:
            im = self.cierre(t - T_HOOK - self.n * T_PROD)
        d = ImageDraw.Draw(im, 'RGBA')   # barra de progreso arriba
        d.rounded_rectangle((60, 60, W - 60, 70), radius=5, fill=(255, 255, 255, 60))
        d.rounded_rectangle((60, 60, 60 + (W - 120) * min(1, t / self.dur), 70), radius=5, fill=(255, 255, 255))
        return im.convert("RGB")


def generar(salida, items, fotos, titulo, subtitulo, total, grid_fotos, musica=None):
    r = Reel(items, fotos, titulo, subtitulo, total, grid_fotos)
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
           "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-"]
    if musica and os.path.exists(musica):
        cmd += ["-i", musica, "-af", f"afade=t=in:d=0.3,afade=t=out:st={max(0, r.dur - 1.5):.2f}:d=1.5",
                "-map", "0:v", "-map", "1:a", "-c:a", "aac", "-b:a", "160k", "-shortest"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", salida]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    n = int(r.dur * FPS)
    for k in range(n):
        pr.stdin.write(r.frame(k / FPS).tobytes())
    pr.stdin.close()
    pr.wait(timeout=300)
    # portada = un cuadro del gancho ya armado
    r.hook(1.6).convert("RGB").save(salida.replace(".mp4", "-portada.jpg"), quality=90)
    return pr.returncode == 0

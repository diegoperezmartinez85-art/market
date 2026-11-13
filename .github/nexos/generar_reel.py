"""
Nexos Market - Reel diario (video vertical 1080x1920) con las ofertas del kit.

Usa las imágenes historia-N.jpg ya generadas, agrega una portada y un cierre,
y las une con transiciones suaves usando ffmpeg. Sin música: se le pone una
desde la biblioteca de Instagram al subirlo (así no hay problemas de derechos).
"""
import os
import shutil
import subprocess
import time

import generar_ofertas as go

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

W, H = 1080, 1920
DUR = 2.6      # segundos por oferta
FADE = 0.4


def _centrado(d, y, texto, fnt, color):
    # achica la letra si el texto no entra en el ancho
    try:
        while d.textlength(texto, font=fnt) > W - 120 and fnt.size > 30:
            fnt = fnt.font_variant(size=fnt.size - 4)
    except AttributeError:
        pass
    d.text(((W - d.textlength(texto, font=fnt)) / 2, y), texto, font=fnt, fill=color)


def _tarjeta_foto(foto, w, h):
    """Foto del producto sobre tarjeta blanca redondeada (RGBA)."""
    from PIL import Image as _I, ImageDraw as _D
    card = _I.new("RGBA", (w, h), (0, 0, 0, 0))
    _D.Draw(card).rounded_rectangle((0, 0, w - 1, h - 1), radius=44, fill=(255, 255, 255, 255))
    if foto is not None:
        ph = go.encajar(foto, w - 60, h - 60).convert("RGBA")
        card.alpha_composite(ph, ((w - ph.width) // 2, (h - ph.height) // 2))
    return card


def portada(n, path, l1=None, l2=None, l3=None, fotos=None):
    im = Image.new("RGB", (W, H), go.BG)
    d = ImageDraw.Draw(im)
    fotos = [f for f in (fotos or []) if f is not None][:3]
    if fotos:
        # halo de color detrás del collage
        from PIL import ImageFilter
        glow = Image.new("RGB", (W, H), go.BG)
        gd = ImageDraw.Draw(glow)
        gd.ellipse((140, 380, 940, 1100), fill=(58, 109, 240))
        gd.ellipse((380, 520, 1020, 1120), fill=(224, 25, 138))
        im = Image.blend(im, glow.filter(ImageFilter.GaussianBlur(160)), 0.55)
        d = ImageDraw.Draw(im)
        go.marca(im, d, 140, x=(W - 330) // 2)
        base = im.convert("RGBA")
        lados = [(fotos[1] if len(fotos) > 1 else None, -8, 250), (fotos[2] if len(fotos) > 2 else None, 8, 830)]
        for foto, ang, cx in lados:
            if foto is None:
                continue
            c = _tarjeta_foto(foto, 360, 430).rotate(ang, expand=True, resample=Image.BICUBIC)
            base.alpha_composite(c, (cx - c.width // 2, 480))
        c = _tarjeta_foto(fotos[0], 540, 640)
        base.alpha_composite(c, ((W - c.width) // 2, 330))
        im = base.convert("RGB")
        d = ImageDraw.Draw(im)
        y = 1050
    else:
        go.marca(im, d, 200, x=(W - 330) // 2)
        y = 620
    _centrado(d, y, l1 or f"{n} ofertas", go.font("Black", 120 if l1 else 140), go.WHITE)
    _centrado(d, y + 165, l2 or "que bajaron de precio", go.font("Black", 88), go.CYAN)
    _centrado(d, y + 290, l3 or "en Mercado Libre", go.font("Bold", 64), go.MUTED)
    py = y + 420
    d.rounded_rectangle((240, py, W - 240, py + 100), radius=50, fill=go.GREEN)
    _centrado(d, py + 23, "Precios del " + time.strftime("%d/%m"), go.font("Bold", 48), go.WHITE)
    im.save(path, quality=90)


def cierre(path):
    im = Image.new("RGB", (W, H), go.BG)
    d = ImageDraw.Draw(im)
    go.marca(im, d, 200, x=(W - 330) // 2)
    _centrado(d, 640, "¿Te sirvió?", go.font("Black", 120), go.WHITE)
    _centrado(d, 820, "Seguinos para ver", go.font("Bold", 64), go.MUTED)
    _centrado(d, 900, "las ofertas de cada día", go.font("Bold", 64), go.MUTED)
    d.rounded_rectangle((140, 1100, W - 140, 1220), radius=60, fill=go.BLUE)
    _centrado(d, 1128, "Link en la bio", go.font("Black", 60), go.WHITE)
    _centrado(d, 1290, "market.nexosmaps.com", go.font("Bold", 48), go.CYAN)
    im.save(path, quality=90)


def generar(kdir, n, historias=None, salida="reel.mp4", textos=None, fotos=None):
    """Crea kdir/reel.mp4 (y reel-portada.jpg). Devuelve True si salió bien."""
    if not (Image and shutil.which("ffmpeg") and n):
        return False
    tmp = os.path.join(kdir, "_reel")
    os.makedirs(tmp, exist_ok=True)
    try:
        frames = [os.path.join(kdir, salida.replace(".mp4", "-portada.jpg"))]
        portada(n, frames[0], *(textos or (None, None, None)), fotos=fotos)
        frames += historias or [os.path.join(kdir, f"historia-{i}.jpg") for i in range(1, n + 1)
                                if os.path.exists(os.path.join(kdir, f"historia-{i}.jpg"))]
        frames.append(os.path.join(tmp, "cierre.jpg"))
        cierre(frames[-1])
        durs = [2.2] + [DUR] * (len(frames) - 2) + [2.4]
        cmd = ["ffmpeg", "-y", "-loglevel", "error"]
        for f, t in zip(frames, durs):
            cmd += ["-loop", "1", "-t", f"{t + FADE:.2f}", "-i", f]
        partes, prev, off = [], "0:v", 0.0
        for i in range(len(frames)):
            partes.append(f"[{i}:v]scale={W}:{H},setsar=1,format=yuv420p,fps=30[v{i}]")
        prev = "v0"
        for i in range(1, len(frames)):
            off += durs[i - 1]
            out = f"x{i}"
            partes.append(f"[{prev}][v{i}]xfade=transition=fade:duration={FADE}:offset={off:.2f}[{out}]")
            prev = out
        audio = None
        try:
            import musica
            total = sum(durs) + FADE
            audio = musica.generar(total, os.path.join(tmp, "musica.wav"), semilla=int(time.strftime("%j")) + len(salida))
            cmd += ["-i", audio]
        except Exception as e:
            print("musica:", e)
        cmd += ["-filter_complex", ";".join(partes), "-map", f"[{prev}]"]
        if audio:
            cmd += ["-map", f"{len(frames)}:a", "-c:a", "aac", "-b:a", "160k", "-shortest"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", os.path.join(kdir, salida)]
        subprocess.run(cmd, check=True, timeout=300)
        return True
    except Exception as e:
        print("reel:", e)
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

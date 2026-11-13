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
    d.text(((W - d.textlength(texto, font=fnt)) / 2, y), texto, font=fnt, fill=color)


def portada(n, path):
    im = Image.new("RGB", (W, H), go.BG)
    d = ImageDraw.Draw(im)
    go.marca(im, d, 200, x=(W - 330) // 2)
    _centrado(d, 620, f"{n} ofertas", go.font("Black", 140), go.WHITE)
    _centrado(d, 790, "que bajaron de precio", go.font("Black", 88), go.CYAN)
    _centrado(d, 960, "en Mercado Libre", go.font("Bold", 64), go.MUTED)
    d.rounded_rectangle((240, 1180, W - 240, 1280), radius=50, fill=go.GREEN)
    _centrado(d, 1203, "Precios del " + time.strftime("%d/%m"), go.font("Bold", 48), go.WHITE)
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


def generar(kdir, n):
    """Crea kdir/reel.mp4 (y reel-portada.jpg). Devuelve True si salió bien."""
    if not (Image and shutil.which("ffmpeg") and n):
        return False
    tmp = os.path.join(kdir, "_reel")
    os.makedirs(tmp, exist_ok=True)
    try:
        frames = [os.path.join(kdir, "reel-portada.jpg")]
        portada(n, frames[0])
        frames += [os.path.join(kdir, f"historia-{i}.jpg") for i in range(1, n + 1)
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
        cmd += ["-filter_complex", ";".join(partes), "-map", f"[{prev}]",
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", os.path.join(kdir, "reel.mp4")]
        subprocess.run(cmd, check=True, timeout=300)
        return True
    except Exception as e:
        print("reel:", e)
        return False
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

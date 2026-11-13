"""
Nexos Market - Ofertas del día y kit para redes (se genera solo todos los días).

Crea, dentro de la carpeta del sitio:
  ofertas/index.html     página pública "Bajaron de precio" (para compartir y para Google).
  ofertas/og.jpg         imagen que se ve al compartir esa página.
  ofertas/kit/           el kit diario para publicar (no se indexa en Google):
      index.html         página para el celular: descargar, copiar texto y compartir.
      post-N.jpg         imagen 1080x1350 (Instagram / Facebook / WhatsApp).
      historia-N.jpg     imagen 1080x1920 (Estados de WhatsApp / Historias).
      textos.txt         textos listos para pegar.

Todos los links llevan a las páginas de producto de la tienda (p/...), así cada clic es una visita.
"""
import html
import io
import json
import os
import sys
import time
from urllib.parse import quote

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, AQUI)
import generar_paginas as gp  # noqa: E402

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:          # sin Pillow igual se generan las páginas
    Image = None
try:
    import requests
except ImportError:
    requests = None

SITE = gp.SITE_URL
E = gp.E
money = gp.money
KIT_N = 5            # publicaciones por día
INSTAGRAM = "https://www.instagram.com/nexos.marketofertas/"
CANAL = "https://whatsapp.com/channel/0029Vb97B2I2v1IlIV2BFu1w"   # canal de WhatsApp de ofertas
FONTS = os.path.join(AQUI, "fonts")

BG = (15, 19, 22)
WHITE = (255, 255, 255)
MUTED = (150, 160, 172)
GREEN = (15, 160, 80)
BLUE = (47, 95, 227)
CYAN = (122, 162, 255)


# ---------------------------------------------------------------- selección
def pct(p):
    pr, pv = p.get("price"), p.get("prev_price")
    if isinstance(pr, (int, float)) and isinstance(pv, (int, float)) and pv > pr > 0:
        v = round((1 - pr / pv) * 100)
        return v if v >= 3 else 0
    return 0


def vivos(products):
    return [p for p in products
            if p.get("status") != "no_disponible" and isinstance(p.get("price"), (int, float)) and p.get("price") > 0]


def bajas(products):
    b = [p for p in vivos(products) if pct(p)]
    b.sort(key=lambda p: (-pct(p), p.get("name") or ""))
    return b


def kit_del_dia(products, n=KIT_N):
    """Primero lo que bajó en los últimos 2 días; después se rota la lista para que cada día sea distinto."""
    hoy = time.strftime("%Y-%m-%d")
    ayer = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    b = bajas(products)
    recientes = [p for p in b if (p.get("price_drop") or "")[:10] in (hoy, ayer)]
    resto = [p for p in b if p not in recientes]
    otros = sorted([p for p in vivos(products) if p not in b], key=lambda p: p.get("added") or "", reverse=True)
    pool = resto + otros
    if pool:
        k = int(time.strftime("%j")) * n % len(pool)
        pool = pool[k:] + pool[:k]
    return (recientes + pool)[:n]


# ---------------------------------------------------------------- imágenes
def font(peso, tam):
    try:
        return ImageFont.truetype(os.path.join(FONTS, f"Inter-{peso}.otf"), tam)
    except OSError:
        return ImageFont.load_default()


def bajar_imagen(url):
    if not (requests and url):
        return None
    for u in (gp.jpg(url), url):
        try:
            r = requests.get(u, timeout=20, headers={"User-Agent": "Mozilla/5.0 (NexosMarket)"})
            if r.ok and r.content:
                return Image.open(io.BytesIO(r.content)).convert("RGB")
        except Exception:
            pass
    return None


def placeholder(w, h):
    im = Image.new("RGB", (w, h), (238, 241, 245))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((w * .3, h * .3, w * .7, h * .7), radius=30, outline=(200, 206, 214), width=8)
    return im


def encajar(img, w, h):
    """Escala la foto (agrandando si hace falta) para que ocupe el recuadro sin deformarse."""
    k = min(w / img.width, h / img.height)
    return img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)


def wrap(draw, texto, fnt, ancho, max_lineas):
    palabras, lineas, cur = (texto or "").split(), [], ""
    for w in palabras:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=fnt) <= ancho:
            cur = t
        else:
            if cur:
                lineas.append(cur)
            cur = w
            if len(lineas) == max_lineas:
                break
    if cur and len(lineas) < max_lineas:
        lineas.append(cur)
    usadas = " ".join(lineas).split()
    if len(usadas) < len(palabras) and lineas:
        last = lineas[-1]
        while last and draw.textlength(last + "…", font=fnt) > ancho:
            last = last.rsplit(" ", 1)[0] if " " in last else last[:-1]
        lineas[-1] = last.rstrip(",.;:-") + "…"
    return lineas


def pegar_logo(im, x, y, tam):
    try:
        lg = Image.open(os.path.join(gp.BASE_DIR, "..", "..", "logo.jpg")).convert("RGB").resize((tam, tam))
    except OSError:
        return
    m = Image.new("L", (tam, tam), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, tam, tam), radius=tam // 4, fill=255)
    im.paste(lg, (x, y), m)


def marca(im, d, y, x=60):
    pegar_logo(im, x, y, 76)
    f1, f2 = font("ExtraBold", 46), font("Medium", 46)
    d.text((x + 96, y + 12), "Nexos", font=f1, fill=WHITE)
    d.text((x + 96 + d.textlength("Nexos ", font=f1), y + 12), "Market", font=f2, fill=CYAN)


def pill(d, x_der, y, texto, color):
    f = font("Bold", 30)
    w = d.textlength(texto, font=f) + 44
    d.rounded_rectangle((x_der - w, y, x_der, y + 60), radius=30, fill=color)
    d.text((x_der - w + 22, y + 13), texto, font=f, fill=WHITE)


def tarjeta(p, foto, historia=False):
    W, H = (1080, 1920) if historia else (1080, 1350)
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    top = 150 if historia else 50
    marca(im, d, top)
    pc = pct(p)
    pill(d, W - 60, top + 8, "BAJÓ DE PRECIO" if pc else "RECOMENDADO", GREEN if pc else BLUE)

    # foto sobre panel blanco
    px0, py0 = 60, top + 120
    px1, py1 = W - 60, py0 + (900 if historia else 700)
    d.rounded_rectangle((px0, py0, px1, py1), radius=40, fill=WHITE)
    pad = 50
    fw, fh = px1 - px0 - 2 * pad, py1 - py0 - 2 * pad
    ph = encajar(foto or placeholder(fw, fh), fw, fh)
    im.paste(ph, (px0 + pad + (fw - ph.width) // 2, py0 + pad + (fh - ph.height) // 2))
    if pc:
        fb = font("Black", 64)
        t = f"-{pc}%"
        bw = d.textlength(t, font=fb) + 48
        d.rounded_rectangle((px0 + 26, py0 + 26, px0 + 26 + bw, py0 + 26 + 96), radius=24, fill=GREEN)
        d.text((px0 + 50, py0 + 38), t, font=fb, fill=WHITE)

    # textos
    y = py1 + 40
    fn = font("Bold", 46)
    for ln in wrap(d, p.get("name"), fn, W - 120, 2):
        d.text((60, y), ln, font=fn, fill=WHITE)
        y += 58
    y += 18
    if pc:
        fa = font("Medium", 38)
        t = "Antes " + money(p.get("prev_price"))
        d.text((60, y), t, font=fa, fill=MUTED)
        tw = d.textlength(t, font=fa)
        d.line((60, y + 24, 60 + tw, y + 24), fill=MUTED, width=3)
        y += 52
    d.text((56, y), money(p.get("price")), font=font("Black", 104), fill=WHITE)

    # pie
    fy = H - (300 if historia else 120)
    d.rounded_rectangle((60, fy, W - 60, fy + 84), radius=42, fill=BLUE)
    ft = font("Bold", 34)
    t = "Tocá el link y miralo en Mercado Libre" if historia else "Compra protegida en Mercado Libre"
    d.text(((W - d.textlength(t, font=ft)) / 2, fy + 21), t, font=ft, fill=WHITE)
    fu = font("Medium", 32)
    u = "market.nexosmaps.com · precio del " + time.strftime("%d/%m")
    if historia:
        d.text(((W - d.textlength(u, font=fu)) / 2, fy + 112), u, font=fu, fill=MUTED)
    return im


def og_ofertas(lista, fotos):
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    marca(im, d, 40)
    d.text((60, 150), "Bajaron de precio", font=font("Black", 76), fill=WHITE)
    d.text((60, 245), "Ofertas revisadas todos los días · Mercado Libre", font=font("Medium", 34), fill=MUTED)
    x = 60
    for p in lista[:3]:
        d.rounded_rectangle((x, 320, x + 340, 590), radius=28, fill=WHITE)
        ph = encajar(fotos.get(p.get("code")) or placeholder(300, 230), 300, 230)
        im.paste(ph, (x + 20 + (300 - ph.width) // 2, 340 + (230 - ph.height) // 2))
        if pct(p):
            t = f"-{pct(p)}%"
            fb = font("Black", 40)
            bw = d.textlength(t, font=fb) + 30
            d.rounded_rectangle((x + 14, 334, x + 14 + bw, 394), radius=16, fill=GREEN)
            d.text((x + 29, 341), t, font=fb, fill=WHITE)
        x += 370
    return im


# ---------------------------------------------------------------- textos
def url_prod(p):
    return SITE + gp.page_name(p)


def texto(p):
    pc = pct(p)
    cab = f"🔥 Bajó {pc}%" if pc else "⭐ Recomendado"
    precio = (f"Antes {money(p.get('prev_price'))} → Ahora {money(p.get('price'))}" if pc
              else f"Ahora {money(p.get('price'))}")
    return f"{cab}: {p.get('name')}\n{precio}\n👉 {url_prod(p)}"


# ---------------------------------------------------------------- páginas
def cabecera():
    """Usa el mismo encabezado (logo) que las páginas de producto."""
    muestra = gp.render_page({"name": "x", "code": "x", "price": 1, "category": "x"}, [])
    i, j = muestra.index("<header>"), muestra.index("</header>") + len("</header>")
    return muestra[i:j]


CSS_OF = gp.CSS + """
.intro{margin:4px 0 18px;color:var(--muted)}
h1{font-size:1.6rem}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:12px}
.card{position:relative;display:flex;flex-direction:column;background:#fff;border:1px solid var(--line);border-radius:16px;padding:10px;text-decoration:none;color:var(--ink)}
.card img{width:100%;aspect-ratio:1/1;object-fit:contain;background:#f7f8fa;border-radius:12px}
.card .b{position:absolute;top:16px;left:16px;background:var(--green);color:#fff;font-weight:800;border-radius:8px;padding:2px 8px;font-size:.9rem}
.card s{color:var(--muted);font-size:.82rem;margin-top:8px}
.card b{font-size:1.15rem}
.card span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:.85rem;margin-top:2px}
.kit{display:grid;gap:18px}
.item{background:#fff;border:1px solid var(--line);border-radius:18px;padding:14px;display:grid;grid-template-columns:minmax(0,220px) minmax(0,1fr);gap:16px}
.item img{width:100%;border-radius:12px;display:block}
.item pre{white-space:pre-wrap;font:inherit;font-size:.92rem;background:#f7f8fa;border-radius:10px;padding:10px;margin:0 0 10px}
.acts{display:flex;flex-wrap:wrap;gap:8px}
.acts a,.acts button{border:0;border-radius:10px;padding:10px 12px;font:700 .9rem system-ui,sans-serif;cursor:pointer;text-decoration:none;background:#eef3fe;color:#1a56c9}
.acts .pri{background:var(--action);color:#fff}
.canal{display:block;text-align:center;text-decoration:none;background:#128c4b;color:#fff;font-weight:700;border-radius:12px;padding:12px;margin:14px 0}
.ig{display:block;text-align:center;text-decoration:none;background:linear-gradient(90deg,#f58529,#dd2a7b,#8134af);color:#fff;font-weight:700;border-radius:12px;padding:12px;margin:-4px 0 14px}
.tip{background:#fff8e6;border:1px solid #f3dfa6;border-radius:12px;padding:10px 12px;font-size:.9rem;margin-bottom:16px}
@media(max-width:600px){.item{grid-template-columns:1fr}}
"""


def pagina_ofertas(lista, nuevos):
    url = SITE + "ofertas/"
    fecha = time.strftime("%d/%m/%Y")
    cards = "".join(
        f'<a class="card" href="../{E(gp.page_name(p))}"><img src="{E(p.get("image"))}" alt="{E(p.get("name"))}" '
        f'loading="lazy" referrerpolicy="no-referrer"><i class="b">-{pct(p)}%</i>'
        f'<s>Antes {E(money(p.get("prev_price")))}</s><b>{E(money(p.get("price")))}</b><span>{E(p.get("name"))}</span></a>'
        for p in lista)
    cards_n = "".join(
        f'<a class="card" href="../{E(gp.page_name(p))}"><img src="{E(p.get("image"))}" alt="{E(p.get("name"))}" '
        f'loading="lazy" referrerpolicy="no-referrer"><b>{E(money(p.get("price")))}</b><span>{E(p.get("name"))}</span></a>'
        for p in nuevos)
    titulo = f"Ofertas de hoy: {len(lista)} productos que bajaron de precio"
    desc = (f"Productos de Mercado Libre que bajaron de precio, revisados el {fecha}. "
            "Compra protegida en Mercado Libre. Nexos Market revisa los precios todos los días.")
    wa = "https://api.whatsapp.com/send?text=" + quote(f"Mirá las ofertas de hoy 👉 {url}")
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(titulo)} | {gp.MARCA}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{gp.MARCA}">
<meta property="og:locale" content="es_AR">
<meta property="og:title" content="{E(titulo)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{url}og.jpg?v={time.strftime('%Y%m%d')}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<style>{CSS_OF}</style>
</head>
<body>
{cabecera()}
<main>
<p class="crumb"><a href="../">Inicio</a> &rsaquo; Ofertas de hoy</p>
<h1>Bajaron de precio</h1>
<p class="intro">{len(lista)} productos más baratos que cuando los empezamos a seguir. Precios revisados el {fecha}; el precio final lo confirma Mercado Libre.</p>
<div class="grid">{cards}</div>
<a class="canal" href="{CANAL}" target="_blank" rel="noopener">🔔 Seguí el canal de ofertas en WhatsApp</a>
<a class="ig" href="{INSTAGRAM}" target="_blank" rel="noopener">📸 Seguinos en Instagram @nexos.marketofertas</a>
{f'<h2>Recién agregados</h2><div class="grid">{cards_n}</div>' if cards_n else ''}
<a class="wa" href="{wa}" target="_blank" rel="noopener">Compartir estas ofertas por WhatsApp</a>
<a class="all" href="../">Ver todos los productos &rarr;</a>
<p class="note">Este sitio participa del programa de afiliados de Mercado Libre.</p>
</main>
</body>
</html>
"""


def pagina_kit(kit, con_imagenes, resumen=None, reel=False):
    fecha = time.strftime("%d/%m")
    items = []
    if reel:
        v = time.strftime("%Y%m%d")
        cap = (f"{len(kit)} ofertas de Mercado Libre que bajaron de precio 🔥 Precios del {fecha}.\n"
               "👉 Link en la bio para ver cada una y comprar seguro en Mercado Libre.\n"
               "Seguinos para ver las ofertas de cada día. Contiene links de afiliado.\n\n"
               "#ofertas #mercadolibre #ofertasargentina #regalosdenavidad #ahorro")
        items.append(f'<div class="item"><video src="reel.mp4?v={v}" controls playsinline muted style="width:100%;border-radius:12px"></video>'
                     f'<div><p><b>🎬 Reel del día</b> · subilo a Instagram y elegí una música de la biblioteca</p>'
                     f'<pre id="tr">{E(cap)}</pre><div class="acts"><button class="pri" data-share="reel.mp4" data-type="video/mp4">Compartir Reel</button>'
                     f'<a href="reel.mp4" download>Bajar Reel</a><button data-copy="tr">Copiar texto</button></div></div></div>')
    if resumen:
        v = time.strftime("%Y%m%d")
        img = f'<img src="resumen-post.jpg?v={v}" alt="">' if con_imagenes else ""
        bot = ('<button class="pri" data-share="resumen-historia.jpg">Compartir historia</button>'
               '<button data-share="resumen-post.jpg">Compartir post</button>' if con_imagenes else "")
        items.append(f'<div class="item">{img}<div><p><b>☀️ Resumen de la mañana</b> · dólar, clima y oferta del día</p>'
                     f'<pre id="t0">{E(resumen)}</pre><div class="acts">{bot}<button data-copy="t0">Copiar texto</button>'
                     f'<a href="https://api.whatsapp.com/send?text={E(quote(resumen))}" target="_blank" rel="noopener">Mandar por WhatsApp</a>'
                     '</div></div></div>')
    for i, p in enumerate(kit, 1):
        t = texto(p)
        img = (f'<img src="post-{i}.jpg?v={time.strftime("%Y%m%d")}" alt="">' if con_imagenes
               else f'<img src="{E(p.get("image"))}" alt="" referrerpolicy="no-referrer">')
        botones = (f'<button class="pri" data-share="historia-{i}.jpg">Compartir historia</button>'
                   f'<button data-share="post-{i}.jpg">Compartir post</button>'
                   f'<a href="historia-{i}.jpg" download>Bajar historia</a><a href="post-{i}.jpg" download>Bajar post</a>'
                   if con_imagenes else "")
        items.append(f'<div class="item">{img}<div><pre id="t{i}">{E(t)}</pre><div class="acts">{botones}'
                     f'<button data-copy="t{i}">Copiar texto</button>'
                     f'<a href="https://api.whatsapp.com/send?text={E(quote(t))}" target="_blank" rel="noopener">Mandar por WhatsApp</a>'
                     f'</div></div></div>')
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kit de publicaciones {fecha} | {gp.MARCA}</title>
<meta name="robots" content="noindex, nofollow">
<link rel="icon" type="image/svg+xml" href="../../favicon.svg">
<style>{CSS_OF}</style>
</head>
<body>
{cabecera().replace('href="../"', 'href="../../"')}
<main>
<h1>Kit del día · {fecha}</h1>
<p class="intro">Se arma solo cada mañana con las ofertas que más bajaron.</p>
<p class="tip"><b>Estado de WhatsApp en 10 segundos:</b> tocá «Compartir historia», elegí WhatsApp → Mi estado, y pegá el link del texto (ya queda copiado). Repetí con 2 o 3 productos por día, de mañana y a la tarde.</p>
<div class="kit">{''.join(items)}</div>
<a class="all" href="../">Ver la página de ofertas &rarr;</a>
</main>
<script>
function copiar(id){{const t=document.getElementById(id).innerText;(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(()=>aviso('Texto copiado')).catch(()=>{{const r=document.createRange();r.selectNode(document.getElementById(id));getSelection().removeAllRanges();getSelection().addRange(r);document.execCommand('copy');aviso('Texto copiado')}});return t}}
function aviso(m){{const d=document.createElement('div');d.textContent=m;d.style.cssText='position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#111827;color:#fff;padding:10px 16px;border-radius:999px;font:600 .95rem system-ui;z-index:9';document.body.appendChild(d);setTimeout(()=>d.remove(),1800)}}
document.addEventListener('click',async e=>{{
  const c=e.target.closest('[data-copy]');if(c){{copiar(c.dataset.copy);return}}
  const s=e.target.closest('[data-share]');if(!s)return;
  const pre=s.closest('.item').querySelector('pre');const txt=pre.innerText;
  try{{navigator.clipboard&&navigator.clipboard.writeText(txt)}}catch(_){{}}
  try{{const b=await (await fetch(s.dataset.share)).blob();const f=new File([b],s.dataset.share,{{type:s.dataset.type||'image/jpeg'}});
    if(navigator.canShare&&navigator.canShare({{files:[f]}})){{await navigator.share({{files:[f],text:txt}});return}}}}catch(err){{if(err&&err.name==='AbortError')return}}
  const a=document.createElement('a');a.href=s.dataset.share;a.download=s.dataset.share;a.click();aviso('Imagen descargada · texto copiado');
}});
</script>
</body>
</html>
"""


RANGOS = [(0, 25000, "Hasta $25.000"), (25000, 50000, "De $25.000 a $50.000"),
          (50000, 100000, "De $50.000 a $100.000"), (100000, 300000, "De $100.000 a $300.000"),
          (300000, 10 ** 12, "Más de $300.000")]


def pagina_regalos(products):
    url = SITE + "regalos/"
    vs = vivos(products)
    secciones, total = [], 0
    for lo, hi, titulo in RANGOS:
        grupo = [p for p in vs if lo <= p["price"] < hi]
        grupo.sort(key=lambda p: (-pct(p), -(1 if (p.get("added") or "") >= "2026-11-12" else 0), p["price"]))
        grupo = grupo[:16]
        if not grupo:
            continue
        total += len(grupo)
        cards = "".join(
            f'<a class="card" href="../{E(gp.page_name(p))}"><img src="{E(p.get("image"))}" alt="{E(p.get("name"))}" '
            f'loading="lazy" referrerpolicy="no-referrer">' + (f'<i class="b">-{pct(p)}%</i>' if pct(p) else "")
            + f'<b>{E(money(p.get("price")))}</b><span>{E(p.get("name"))}</span></a>' for p in grupo)
        ancla = gp.slug(titulo)
        secciones.append((ancla, titulo, f'<h2 id="{ancla}">{E(titulo)}</h2><div class="grid">{cards}</div>'))
    nav = " ".join(f'<a href="#{a}">{E(t)}</a>' for a, t, _ in secciones)
    titulo = "Regalos de Navidad 2026 por presupuesto: ideas para todos los bolsillos"
    desc = ("Ideas de regalos para Navidad ordenadas por precio: juguetes, tecnología, belleza y hogar. "
            "Precios revisados todos los días, compra protegida en Mercado Libre.")
    wa = "https://api.whatsapp.com/send?text=" + quote(f"Ideas de regalos para Navidad por presupuesto 🎁 {url}")
    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(titulo)} | {gp.MARCA}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="website">
<meta property="og:site_name" content="{gp.MARCA}">
<meta property="og:locale" content="es_AR">
<meta property="og:title" content="Regalos de Navidad por presupuesto 🎁">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}ofertas/og.jpg?v={time.strftime('%Y%m%d')}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<style>{CSS_OF}
.rng{{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 8px}}.rng a{{background:#fff;border:1px solid var(--line);border-radius:999px;padding:8px 12px;text-decoration:none;color:var(--ink);font-weight:600;font-size:.9rem}}
</style>
</head>
<body>
{cabecera()}
<main>
<p class="crumb"><a href="../">Inicio</a> &rsaquo; Regalos de Navidad</p>
<h1>Regalos de Navidad por presupuesto</h1>
<p class="intro">Elegí cuánto querés gastar y mirá las mejores ideas. {total} productos con precio revisado el {time.strftime('%d/%m')}; pagás y recibís en Mercado Libre.</p>
<nav class="rng">{nav}</nav>
<a class="canal" href="{CANAL}" target="_blank" rel="noopener">🔔 Seguí el canal de ofertas en WhatsApp</a>
<a class="ig" href="{INSTAGRAM}" target="_blank" rel="noopener">📸 Seguinos en Instagram @nexos.marketofertas</a>
{''.join(h for _, _, h in secciones)}
<a class="wa" href="{wa}" target="_blank" rel="noopener">Compartir la lista por WhatsApp</a>
<a class="all" href="../ofertas/">Ver lo que bajó de precio hoy &rarr;</a>
<p class="note">Este sitio participa del programa de afiliados de Mercado Libre.</p>
</main>
</body>
</html>
"""


def agregar_al_sitemap(raiz):
    path = os.path.join(raiz, "sitemap.xml")
    try:
        s = open(path, encoding="utf-8").read()
    except OSError:
        return
    for u in (SITE + "ofertas/", SITE + "regalos/", SITE + "dolar/"):
        if u in s:
            continue
        item = (f"<url><loc>{u}</loc><lastmod>{time.strftime('%Y-%m-%d')}</lastmod>"
                "<changefreq>daily</changefreq><priority>0.9</priority></url>\n")
        s = s.replace("</urlset>", item + "</urlset>")
    open(path, "w", encoding="utf-8").write(s)


def generar(raiz, products, con_imagenes=True):
    odir, kdir = os.path.join(raiz, "ofertas"), os.path.join(raiz, "ofertas", "kit")
    os.makedirs(kdir, exist_ok=True)
    for f in os.listdir(kdir):
        if f.endswith(".jpg"):
            os.remove(os.path.join(kdir, f))
    lista = bajas(products)[:24]
    nuevos = sorted([p for p in vivos(products) if not pct(p)], key=lambda p: p.get("added") or "", reverse=True)[:8]
    kit = kit_del_dia(products)
    hay_img = bool(con_imagenes and Image)

    fotos = {}
    if hay_img:
        for p in {p.get("code"): p for p in kit + lista[:3]}.values():
            fotos[p.get("code")] = bajar_imagen(p.get("image"))
        for i, p in enumerate(kit, 1):
            f = fotos.get(p.get("code"))
            tarjeta(p, f).save(os.path.join(kdir, f"post-{i}.jpg"), quality=88)
            tarjeta(p, f, historia=True).save(os.path.join(kdir, f"historia-{i}.jpg"), quality=88)
        og_ofertas(lista or kit, fotos).save(os.path.join(odir, "og.jpg"), quality=88)
    for f in ("reel.mp4", "reel-portada.jpg"):
        if os.path.exists(os.path.join(kdir, f)):
            os.remove(os.path.join(kdir, f))
    hay_reel = False
    if hay_img:
        try:
            import generar_reel
            hay_reel = generar_reel.generar(kdir, len(kit))
        except Exception as e:
            print("reel:", e)

    with open(os.path.join(odir, "index.html"), "w", encoding="utf-8") as f:
        f.write(pagina_ofertas(lista, nuevos))
    resumen = None
    try:
        import generar_resumen as gr
        resumen = gr.generar(raiz, products, hay_img)
    except Exception as e:          # el resumen nunca frena el resto
        print("resumen:", e)
    if resumen:
        with open(os.path.join(kdir, "resumen.txt"), "w", encoding="utf-8") as f:
            f.write(resumen + "\n")
    with open(os.path.join(kdir, "index.html"), "w", encoding="utf-8") as f:
        f.write(pagina_kit(kit, hay_img, resumen, hay_reel))
    with open(os.path.join(kdir, "textos.txt"), "w", encoding="utf-8") as f:
        f.write(f"Ofertas de hoy en Nexos Market 🛍️ (precios del {time.strftime('%d/%m')}, pueden cambiar)\n\n")
        f.write("\n\n".join(texto(p) for p in kit) + f"\n\nMás ofertas 👉 {SITE}ofertas/\n")
    os.makedirs(os.path.join(raiz, "regalos"), exist_ok=True)
    with open(os.path.join(raiz, "regalos", "index.html"), "w", encoding="utf-8") as f:
        f.write(pagina_regalos(products))
    agregar_al_sitemap(raiz)
    return {"ofertas": len(lista), "kit": len(kit), "fotos_ok": sum(1 for v in fotos.values() if v), "resumen": bool(resumen), "reel": hay_reel}


if __name__ == "__main__":
    raiz = sys.argv[1] if len(sys.argv) > 1 else os.path.abspath(os.path.join(AQUI, "..", ".."))
    with open(os.path.join(raiz, "productos.json"), encoding="utf-8") as fh:
        print(generar(raiz, json.load(fh)))

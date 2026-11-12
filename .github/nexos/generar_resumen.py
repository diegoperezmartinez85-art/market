"""
Nexos Market - Resumen de la mañana (dólar + clima + oferta del día) y página "Dólar hoy".

Datos (gratis, los mismos que usa la tienda):
  dolarapi.com     cotizaciones oficial, blue, MEP, tarjeta.
  open-meteo.com   pronóstico del día para Tres de Febrero.
Si alguna fuente no responde, esa parte simplemente no se muestra.
"""
import html
import os
import time
from urllib.parse import quote

import generar_ofertas as go
import generar_paginas as gp

try:
    import requests
except ImportError:
    requests = None
try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None

SITE = gp.SITE_URL
E = gp.E
LAT, LON, ZONA = -34.605, -58.563, "Tres de Febrero"
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
CASAS = [("oficial", "Oficial"), ("blue", "Blue"), ("bolsa", "MEP"), ("tarjeta", "Tarjeta")]

# códigos WMO de open-meteo -> texto corto
WMO = {0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado", 3: "Nublado",
       45: "Niebla", 48: "Niebla", 51: "Llovizna", 53: "Llovizna", 55: "Llovizna",
       61: "Lluvia débil", 63: "Lluvia", 65: "Lluvia fuerte", 80: "Chaparrones", 81: "Chaparrones",
       82: "Chaparrones fuertes", 95: "Tormenta", 96: "Tormenta con granizo", 99: "Tormenta con granizo"}


def _get(url):
    if not requests:
        return None
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "NexosMarket/1.0"})
        return r.json() if r.ok else None
    except Exception:
        return None


def dolar():
    data = _get("https://dolarapi.com/v1/dolares") or []
    por_casa = {d.get("casa"): d for d in data if isinstance(d, dict)}
    out = []
    for casa, nombre in CASAS:
        d = por_casa.get(casa)
        if d and isinstance(d.get("venta"), (int, float)):
            out.append({"casa": casa, "nombre": nombre, "compra": d.get("compra"), "venta": d["venta"]})
    return out


def clima():
    j = _get(f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
             "&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
             "&timezone=America%2FArgentina%2FBuenos_Aires&forecast_days=1")
    try:
        d = j["daily"]
        return {"max": round(d["temperature_2m_max"][0]), "min": round(d["temperature_2m_min"][0]),
                "lluvia": d["precipitation_probability_max"][0], "estado": WMO.get(d["weathercode"][0], "")}
    except (TypeError, KeyError, IndexError):
        return None


def money(v):
    return gp.money(v)


def fecha_larga():
    t = time.localtime()
    return f"{DIAS[t.tm_wday].capitalize()} {t.tm_mday}/{t.tm_mon}"


def oferta_del_dia(products):
    b = go.bajas(products)
    return b[0] if b else (go.kit_del_dia(products, 1) or [None])[0]


def texto(dol, cli, p):
    lineas = [f"☀️ Buen día · {fecha_larga()}", ""]
    if dol:
        lineas.append("💵 Dólar hoy (venta)")
        lineas += [f"• {d['nombre']}: {money(d['venta'])}" for d in dol]
        lineas.append("")
    if cli:
        lineas.append(f"🌤️ {ZONA}: {cli['estado']}, {cli['min']}° a {cli['max']}°"
                      + (f" · lluvia {cli['lluvia']}%" if cli.get("lluvia") else ""))
        lineas.append("")
    if p:
        pc = go.pct(p)
        lineas.append(f"🔥 Oferta del día{' (-' + str(pc) + '%)' if pc else ''}: {p.get('name')} a {money(p.get('price'))}")
        lineas.append(f"👉 {go.url_prod(p)}")
        lineas.append("")
    lineas.append(f"💱 Conversor y cotizaciones: {SITE}dolar/")
    return "\n".join(lineas)


def tarjeta(dol, cli, p, foto, historia=False):
    W, H = (1080, 1920) if historia else (1080, 1350)
    im = Image.new("RGB", (W, H), go.BG)
    d = ImageDraw.Draw(im)
    top = 150 if historia else 50
    go.marca(im, d, top)
    go.pill(d, W - 60, top + 8, fecha_larga().upper(), go.BLUE)
    y = top + 130
    d.text((60, y), "Buen día", font=go.font("Black", 84 if historia else 72), fill=go.WHITE)
    y += 120 if historia else 100

    if dol:   # tarjetas del dólar, 2 por fila
        cw, ch = (W - 120 - 20) // 2, 150 if historia else 128
        for i, c in enumerate(dol[:4]):
            x0 = 60 + (i % 2) * (cw + 20)
            y0 = y + (i // 2) * (ch + 20)
            d.rounded_rectangle((x0, y0, x0 + cw, y0 + ch), radius=26, fill=(28, 34, 40))
            d.text((x0 + 26, y0 + 18), f"Dólar {c['nombre']}", font=go.font("Bold", 32), fill=go.MUTED)
            d.text((x0 + 24, y0 + (62 if historia else 54)), money(c["venta"]), font=go.font("Black", 58 if historia else 52), fill=go.WHITE)
        y += 2 * (ch + 20) + 10
    if cli:
        d.rounded_rectangle((60, y, W - 60, y + 110), radius=26, fill=(28, 34, 40))
        t = f"{cli['estado']} · {cli['min']}° a {cli['max']}°" + (f" · lluvia {cli['lluvia']}%" if cli.get("lluvia") else "")
        d.text((86, y + 16), ZONA, font=go.font("Bold", 30), fill=go.MUTED)
        d.text((86, y + 54), t, font=go.font("Bold", 40), fill=go.WHITE)
        y += 140
    if p:   # oferta del día
        disp = (H - (330 if historia else 150)) - y
        if disp > 260:
            d.rounded_rectangle((60, y, W - 60, y + disp), radius=30, fill=go.WHITE)
            lado = min(disp - 40, 420)
            ph = go.encajar(foto or go.placeholder(lado, lado), lado, lado)
            im.paste(ph, (80 + (lado - ph.width) // 2, y + 20 + (lado - ph.height) // 2))
            tx = 80 + lado + 30
            ancho = W - 90 - tx
            d.text((tx, y + 26), "OFERTA DEL DÍA", font=go.font("Black", 30), fill=go.GREEN if go.pct(p) else go.BLUE)
            yy = y + 74
            for ln in go.wrap(d, p.get("name"), go.font("Bold", 34), ancho, 3):
                d.text((tx, yy), ln, font=go.font("Bold", 34), fill=(17, 24, 39))
                yy += 44
            yy += 10
            if go.pct(p):
                d.text((tx, yy), f"-{go.pct(p)}%", font=go.font("Black", 44), fill=go.GREEN)
                yy += 56
            d.text((tx, yy), money(p.get("price")), font=go.font("Black", 54), fill=(17, 24, 39))
    fy = H - (300 if historia else 120)
    d.rounded_rectangle((60, fy, W - 60, fy + 84), radius=42, fill=go.BLUE)
    t = "Conversor y ofertas en market.nexosmaps.com"
    ft = go.font("Bold", 32)
    d.text(((W - d.textlength(t, font=ft)) / 2, fy + 23), t, font=ft, fill=go.WHITE)
    return im


def pagina_dolar(dol, products):
    url = SITE + "dolar/"
    fecha = time.strftime("%d/%m/%Y %H:%M")
    filas = "".join(f'<tr><td>Dólar {E(c["nombre"])}</td><td data-c="{E(c["casa"])}" data-k="compra">{E(money(c["compra"]) if c.get("compra") else "-")}</td>'
                    f'<td data-c="{E(c["casa"])}" data-k="venta"><b>{E(money(c["venta"]))}</b></td></tr>' for c in dol)
    blue = next((c["venta"] for c in dol if c["casa"] == "blue"), None)
    ofertas = go.bajas(products)[:8] or go.kit_del_dia(products, 8)
    cards = "".join(
        f'<a class="card" href="../{E(gp.page_name(p))}"><img src="{E(p.get("image"))}" alt="{E(p.get("name"))}" '
        f'loading="lazy" referrerpolicy="no-referrer">' + (f'<i class="b">-{go.pct(p)}%</i>' if go.pct(p) else "")
        + f'<b>{E(money(p.get("price")))}</b>'
        + (f'<s style="text-decoration:none">≈ US$ {round(p["price"] / blue):,}'.replace(",", ".") + ' (blue)</s>' if blue else "")
        + f'<span>{E(p.get("name"))}</span></a>' for p in ofertas)
    opts = "".join(f'<option value="{E(c["casa"])}" data-v="{c["venta"]}">{E(c["nombre"])}</option>' for c in dol)
    titulo = "Dólar hoy: oficial, blue, MEP y tarjeta + conversor"
    desc = f"Cotización del dólar hoy en Argentina (oficial, blue, MEP y tarjeta), actualizada el {fecha}, con conversor de pesos a dólares."
    wa = "https://api.whatsapp.com/send?text=" + quote(f"Dólar hoy y conversor 💵 {url}")
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
<meta property="og:title" content="Dólar hoy + conversor 💵">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{SITE}ofertas/kit/resumen-post.jpg?v={time.strftime('%Y%m%d')}">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<style>{go.CSS_OF}
table{{width:100%;border-collapse:collapse;background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden}}
td,th{{padding:12px 14px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:.8rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}}
td:not(:first-child),th:not(:first-child){{text-align:right}}
.conv{{background:#fff;border:1px solid var(--line);border-radius:14px;padding:14px;margin-top:16px;display:grid;gap:10px}}
.conv input,.conv select{{font:inherit;font-size:1.1rem;padding:10px 12px;border:1px solid var(--line);border-radius:10px;width:100%}}
.conv .row{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:10px}}
.conv output{{font-size:1.4rem;font-weight:800}}
</style>
</head>
<body>
{go.cabecera()}
<main>
<p class="crumb"><a href="../">Inicio</a> &rsaquo; Dólar hoy</p>
<h1>Dólar hoy</h1>
<p class="intro">Cotizaciones en Argentina. Actualizado: <span id="upd">{fecha}</span>. Fuente: DolarApi.</p>
<table><tr><th>Tipo</th><th>Compra</th><th>Venta</th></tr>{filas}</table>
<div class="conv">
  <b>Conversor</b>
  <div class="row"><input id="monto" type="number" inputmode="decimal" value="100" aria-label="Monto">
  <select id="tipo" aria-label="Tipo de dólar">{opts}</select></div>
  <div class="row"><select id="dir" aria-label="Sentido"><option value="ud">US$ → $</option><option value="du">$ → US$</option></select>
  <output id="res"></output></div>
</div>
{go.CANAL and f'<a class="canal" href="{go.CANAL}" target="_blank" rel="noopener">🔔 Dólar, clima y ofertas todos los días en nuestro canal de WhatsApp</a>'}
<h2>Ofertas de hoy{' (con su precio en dólares)' if blue else ''}</h2>
<div class="grid">{cards}</div>
<a class="wa" href="{wa}" target="_blank" rel="noopener">Compartir por WhatsApp</a>
<a class="all" href="../ofertas/">Ver todas las ofertas &rarr;</a>
<p class="note">Cotizaciones de referencia; pueden variar según el banco o la casa de cambio. Este sitio participa del programa de afiliados de Mercado Libre.</p>
</main>
<script>
const fmt=v=>new Intl.NumberFormat('es-AR',{{maximumFractionDigits:2}}).format(v);
function calc(){{const o=document.querySelector('#tipo').selectedOptions[0];if(!o)return;const v=+o.dataset.v,m=+document.querySelector('#monto').value||0;
document.querySelector('#res').textContent=document.querySelector('#dir').value==='ud'?'$ '+fmt(m*v):'US$ '+fmt(m/v)}}
['monto','tipo','dir'].forEach(i=>document.getElementById(i).addEventListener('input',calc));calc();
fetch('https://dolarapi.com/v1/dolares').then(r=>r.json()).then(a=>{{a.forEach(d=>{{
  document.querySelectorAll('[data-c="'+d.casa+'"]').forEach(td=>{{const v=d[td.dataset.k];if(typeof v==='number')td.innerHTML=(td.dataset.k==='venta'?'<b>':'')+'$ '+fmt(v)+(td.dataset.k==='venta'?'</b>':'')}});
  const o=document.querySelector('#tipo option[value="'+d.casa+'"]');if(o&&typeof d.venta==='number')o.dataset.v=d.venta}});
  document.querySelector('#upd').textContent=new Date().toLocaleString('es-AR',{{dateStyle:'short',timeStyle:'short'}})+' (en vivo)';calc()}}).catch(()=>{{}});
</script>
</body>
</html>
"""


def generar(raiz, products, con_imagenes=True):
    """Devuelve el texto del resumen (o None) y escribe imágenes + página del dólar."""
    dol, cli = dolar(), clima()
    p = oferta_del_dia(products)
    if not dol and not cli:
        return None
    kdir = os.path.join(raiz, "ofertas", "kit")
    if con_imagenes and Image:
        foto = go.bajar_imagen(p.get("image")) if p else None
        tarjeta(dol, cli, p, foto).save(os.path.join(kdir, "resumen-post.jpg"), quality=88)
        tarjeta(dol, cli, p, foto, historia=True).save(os.path.join(kdir, "resumen-historia.jpg"), quality=88)
    if dol:
        os.makedirs(os.path.join(raiz, "dolar"), exist_ok=True)
        with open(os.path.join(raiz, "dolar", "index.html"), "w", encoding="utf-8") as f:
            f.write(pagina_dolar(dol, products))
    return texto(dol, cli, p)

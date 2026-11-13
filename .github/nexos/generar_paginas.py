"""
Nexos Market - Generador de páginas para compartir y para Google.

Crea, dentro de la carpeta 'sitio':
  p/<codigo>-<nombre>.html  una página por producto. Al compartirla en WhatsApp,
                            Facebook, Telegram o X se ve la FOTO, el NOMBRE y el PRECIO.
                            Google también la indexa (cada producto puede aparecer en búsquedas).
  sitemap.xml               lista de todas las páginas para Google.
  robots.txt                le dice a Google dónde está el sitemap.
  productos.json            con el campo "page" para que la tienda comparta estas páginas.

Lo usa el gestor al tocar «Publicar online» (y el modo automático). También se puede
correr solo:  python generar_paginas.py
"""
import html
import json
import os
import re
import shutil
import sys
import time
import unicodedata
from urllib.parse import quote

SITE_URL = "https://market.nexosmaps.com/"     # si cambiás de dominio, cambialo acá
MARCA = "Nexos Market"

BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))


def slug(texto, largo=60):
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:largo].rstrip("-") or "producto"


def page_name(p):
    code = (p.get("code") or f"id{p.get('id')}").lower()
    return f"p/{code}-{slug(p.get('name'))}.html"


def money(v):
    if not isinstance(v, (int, float)):
        return "Consultar precio"
    entero = f"{v:,.0f}".replace(",", ".")
    return f"$ {entero}"


def jpg(url):
    """WhatsApp a veces no muestra .webp en la vista previa: Mercado Libre sirve la misma foto en .jpg."""
    return re.sub(r"\.webp$", ".jpg", url or "")


E = lambda s: html.escape(str(s or ""), quote=True)

CSS = """
:root{--bg:#0f1316;--ink:#111827;--muted:#5b6672;--line:#e3e7eb;--action:#2f5fe3;--green:#0f7a3f}
*{box-sizing:border-box;margin:0}
body{font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;background:#f3f5f8;color:var(--ink);line-height:1.45}
header{background:var(--bg);padding:12px 16px;text-align:center}
header .brand{display:inline-flex;align-items:center;gap:10px;color:#fff;text-decoration:none;font-size:1.35rem;letter-spacing:-.03em}
header .brand svg{width:36px;height:36px}
header .brand b{font-weight:800}
header .brand i{font-style:normal;font-weight:500;background:linear-gradient(90deg,#0da9d9,#3a6df0,#7a2fd6,#df005b);-webkit-background-clip:text;background-clip:text;color:transparent}
main{max-width:980px;margin:0 auto;padding:18px 16px 48px}
.crumb{font-size:.85rem;color:var(--muted);margin-bottom:12px}
.crumb a{color:var(--action);text-decoration:none}
.prod{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px;background:#fff;border:1px solid var(--line);border-radius:18px;padding:18px}
.img{background:#f7f8fa;border-radius:14px;aspect-ratio:1/1;display:flex;align-items:center;justify-content:center;overflow:hidden}
.img img{width:100%;height:100%;object-fit:contain}
h1{font-size:1.35rem;line-height:1.25}
.chip{display:inline-block;font-size:.75rem;color:#1a56c9;background:#eef3fe;border:1px solid #cddcfb;border-radius:999px;padding:2px 10px;margin-bottom:8px}
.price{font-size:2rem;font-weight:800;margin:14px 0 2px}
.was{color:var(--muted);text-decoration:line-through;font-size:1rem}
.off{display:inline-block;background:var(--green);color:#fff;font-weight:800;border-radius:10px;padding:4px 10px;margin-left:8px;font-size:1rem}
.cuotas{color:var(--action);font-size:.9rem;font-weight:600}
.btn{display:block;text-align:center;text-decoration:none;background:var(--action);color:#fff;font-weight:700;padding:14px;border-radius:12px;margin-top:16px;font-size:1.05rem}
.btn:hover{background:#244fc4}
.wa{display:block;text-align:center;text-decoration:none;color:#14683f;border:1.5px solid #14683f;border-radius:12px;padding:11px;margin-top:10px;font-weight:700}
.safe{font-size:.85rem;color:#14683f;background:#ecf8f1;border-radius:10px;padding:8px 10px;margin-top:12px}
.off-msg{background:#fdecef;color:#8a1c3d;border-radius:10px;padding:10px 12px;margin-top:14px;font-weight:600}
.note{font-size:.78rem;color:var(--muted);margin-top:12px}
h2{font-size:1.15rem;margin:28px 0 12px}
.rel{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px}
.rel a{display:block;background:#fff;border:1px solid var(--line);border-radius:14px;padding:10px;text-decoration:none;color:var(--ink)}
.rel img{width:100%;aspect-ratio:1/1;object-fit:contain;background:#f7f8fa;border-radius:10px}
.rel b{display:block;margin-top:6px}
.rel span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;font-size:.85rem}
.all{display:block;text-align:center;margin-top:22px;font-weight:700;color:var(--action)}
@media(max-width:680px){.prod{grid-template-columns:1fr;padding:12px}h1{font-size:1.15rem}.price{font-size:1.7rem}}
"""


def render_page(p, relacionados):
    url = SITE_URL + page_name(p)
    caido = p.get("status") == "no_disponible"
    price = p.get("price")
    prev = p.get("prev_price")
    baja = (not caido and isinstance(price, (int, float)) and isinstance(prev, (int, float)) and prev > price
            and (1 - price / prev) * 100 >= 3)   # un -0% parece falso
    pct = round((1 - price / prev) * 100) if baja else 0
    nombre = p.get("name") or "Producto"
    cat = p.get("category") or "Otros"
    precio_txt = money(price)

    titulo = f"{nombre} - {precio_txt}" + (f" (-{pct}%)" if baja else "")
    desc = (f"{'Bajó ' + str(pct) + '%: ' if baja else ''}{nombre} a {precio_txt}. "
            f"Precio actualizado, compra segura en Mercado Libre. Más ofertas de {cat} en {MARCA}.")
    img = p.get("image") or (SITE_URL + "og.jpg")

    ld = {
        "@context": "https://schema.org", "@type": "Product", "name": nombre, "image": [img],
        "category": cat, "sku": p.get("code") or str(p.get("id")), "url": url,
    }
    if isinstance(price, (int, float)):
        ld["offers"] = {"@type": "Offer", "price": price, "priceCurrency": p.get("currency") or "ARS",
                        "url": url, "availability": "https://schema.org/" + ("OutOfStock" if caido else "InStock")}

    wa_txt = f"Mirá esta oferta: {nombre} - {precio_txt}\n{url}"
    wa = "https://api.whatsapp.com/send?text=" + html.escape(
        quote(wa_txt), quote=True)

    rel_html = "".join(
        f'<a href="../{E(page_name(r))}"><img src="{E(r.get("image"))}" alt="{E(r.get("name"))}" loading="lazy" '
        f'referrerpolicy="no-referrer"><b>{E(money(r.get("price")))}</b><span>{E(r.get("name"))}</span></a>'
        for r in relacionados)

    cuotas = ""
    boton = ('<p class="off-msg">Esta publicación ya no está disponible. Mirá productos parecidos abajo.</p>'
             if caido else
             f'<a class="btn" href="{E(p.get("link"))}" rel="nofollow sponsored noopener" target="_blank">'
             f'Ver en Mercado Libre &rarr;</a>'
             f'<a class="wa" href="{wa}" target="_blank" rel="noopener">Compartir por WhatsApp</a>')

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(titulo)} | {MARCA}</title>
<meta name="description" content="{E(desc)}">
<link rel="canonical" href="{E(url)}">
<meta name="robots" content="{'noindex, follow' if caido else 'index, follow, max-image-preview:large'}">
<meta property="og:type" content="product">
<meta property="og:site_name" content="{MARCA}">
<meta property="og:locale" content="es_AR">
<meta property="og:title" content="{E(titulo)}">
<meta property="og:description" content="{E(desc)}">
<meta property="og:url" content="{E(url)}">
<meta property="og:image" content="{E(jpg(img))}">
<meta property="product:price:amount" content="{E(price if isinstance(price, (int, float)) else '')}">
<meta property="product:price:currency" content="{E(p.get('currency') or 'ARS')}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{E(titulo)}">
<meta name="twitter:description" content="{E(desc)}">
<meta name="twitter:image" content="{E(jpg(img))}">
<link rel="icon" type="image/svg+xml" href="../favicon.svg">
<link rel="icon" type="image/png" href="../favicon.png">
<script type="application/ld+json">{json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")}</script>
<style>{CSS}</style>
</head>
<body>
<header><a href="../" class="brand"><svg viewBox="0 0 64 64" aria-hidden="true"><defs>
<linearGradient id="pnxBg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#22d3f5"/><stop offset=".55" stop-color="#3a6df0"/><stop offset="1" stop-color="#6b3fe0"/></linearGradient>
<linearGradient id="pnxPin" x1="0" y1="0" x2="1" y2=".9"><stop offset="0" stop-color="#8b3dff"/><stop offset=".55" stop-color="#e0198a"/><stop offset="1" stop-color="#ff2d6f"/></linearGradient>
<radialGradient id="pnxGlow" cx=".25" cy=".15" r=".9"><stop offset="0" stop-color="#fff" stop-opacity=".35"/><stop offset=".6" stop-color="#fff" stop-opacity="0"/></radialGradient>
</defs>
<rect x="2" y="2" width="60" height="60" rx="16" fill="url(#pnxBg)"/>
<rect x="2" y="2" width="60" height="60" rx="16" fill="url(#pnxGlow)"/>
<path d="M2 40c14-6 26 8 60-2v8c0 8.8-7.2 16-16 16H18c-8.8 0-16-7.2-16-16Z" fill="#fff" opacity=".08"/>
<g transform="translate(32 33) scale(1.17) translate(-32 -33)"><ellipse cx="32" cy="53.5" rx="8" ry="1.8" fill="#ff5fa8" opacity=".75"/>
<path d="M32 52C26 44.6 17.5 37.6 17.5 27.5a14.5 14.5 0 0 1 29 0C46.5 37.6 38 44.6 32 52Z" fill="url(#pnxPin)"/>
<path d="M32 13a14.5 14.5 0 0 1 14.5 14.5c0 4-1.4 7.6-3.5 11L32 13Z" fill="#fff" opacity=".12"/>
<circle cx="32" cy="27" r="5.6" fill="#1a1433"/></g></svg><b>Nexos</b> <i>Market</i></a></header>
<main>
<p class="crumb"><a href="../">Inicio</a> &rsaquo; <a href="../?cat={E(quote(cat))}">{E(cat)}</a></p>
<article class="prod">
  <div class="img"><img src="{E(img)}" alt="{E(nombre)}" referrerpolicy="no-referrer"></div>
  <div>
    <span class="chip">{E(cat)}</span>
    <h1>{E(nombre)}</h1>
    <p class="price">{E(precio_txt)}{f'<span class="off">-{pct}%</span>' if baja else ''}</p>
    {f'<p class="was">Antes {E(money(prev))}</p>' if baja else ''}
    {cuotas}
    <p class="safe"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-3px"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/><path d="m9 12 2 2 4-4"/></svg> Pagás y recibís en Mercado Libre, con su Compra Protegida.</p>
    {boton}
    <p class="note">Código {E(p.get('code'))} · Precio verificado el {E((p.get('checked') or p.get('added') or '')[:10])}. El precio final lo confirma Mercado Libre. Este sitio participa del programa de afiliados de Mercado Libre.</p>
  </div>
</article>
{f'<h2>Más ofertas de {E(cat)}</h2><div class="rel">{rel_html}</div>' if rel_html else ''}
<a class="wa" href="https://whatsapp.com/channel/0029Vb97B2I2v1IlIV2BFu1w" target="_blank" rel="noopener">🔔 Seguí el canal de ofertas en WhatsApp</a>
<a class="all" href="https://www.instagram.com/nexos.marketofertas/" target="_blank" rel="noopener">📸 Seguinos en Instagram @nexos.marketofertas</a>
<a class="all" href="../">Ver todas las ofertas de {MARCA} &rarr;</a>
</main>
</body>
</html>
"""


def generar(site_dir, products):
    """Escribe las páginas, sitemap.xml, robots.txt y productos.json (con 'page') en site_dir."""
    pdir = os.path.join(site_dir, "p")
    if os.path.isdir(pdir):
        shutil.rmtree(pdir)          # productos borrados: su página también se va
    os.makedirs(pdir, exist_ok=True)

    vivos = [p for p in products if p.get("status") != "no_disponible"]
    salida = []
    for p in products:
        q = dict(p)
        q["page"] = page_name(p)
        salida.append(q)
        # relacionados: misma categoría, primero los que bajaron de precio
        rel = [r for r in vivos if r.get("category") == p.get("category") and r.get("id") != p.get("id")]
        rel.sort(key=lambda r: -((r.get("prev_price") or 0) - (r.get("price") or 0)))
        if len(rel) < 4:
            rel += [r for r in vivos if r not in rel and r.get("id") != p.get("id")][:8 - len(rel)]
        with open(os.path.join(site_dir, q["page"]), "w", encoding="utf-8") as f:
            f.write(render_page(p, rel[:8]))

    with open(os.path.join(site_dir, "productos.json"), "w", encoding="utf-8") as f:
        json.dump(salida, f, indent=1, ensure_ascii=False)

    hoy = time.strftime("%Y-%m-%d")
    urls = [(SITE_URL, hoy, "1.0", "daily")]
    for cat in sorted({p.get("category") for p in vivos if p.get("category")}):
        urls.append((SITE_URL + "?cat=" + html.escape(quote(cat)), hoy, "0.7", "daily"))
    for p in vivos:
        fecha = (p.get("checked") or p.get("added") or hoy)[:10]
        urls.append((SITE_URL + page_name(p), fecha, "0.8", "daily"))
    xml = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for u, d, pr, cf in urls:
        xml.append(f"  <url><loc>{u}</loc><lastmod>{d}</lastmod><changefreq>{cf}</changefreq><priority>{pr}</priority></url>")
    xml.append("</urlset>")
    with open(os.path.join(site_dir, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write("\n".join(xml) + "\n")
    with open(os.path.join(site_dir, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(f"User-agent: *\nAllow: /\n\nSitemap: {SITE_URL}sitemap.xml\n")
    return len(salida)


if __name__ == "__main__":
    site = os.path.join(BASE_DIR, "sitio")
    os.makedirs(site, exist_ok=True)
    with open(os.path.join(BASE_DIR, "productos.json"), encoding="utf-8-sig") as f:
        prods = json.load(f)
    n = generar(site, prods)
    print(f"Listo: {n} páginas de producto + sitemap.xml + robots.txt en {site}")

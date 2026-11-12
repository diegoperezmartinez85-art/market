"""
Nexos Market - Gestor de productos
Pegás el enlace de Mercado Libre, se agrega a productos.json y la tienda lo muestra.
También permite eliminar productos y abrir la tienda.
"""
import functools
import html as htmllib
import http.server
import json
import os
import queue
import re
import shutil
import socket
import sys
import threading
import time
import webbrowser
from urllib.parse import unquote, urlsplit

import requests

# Carpeta donde viven index.html y productos.json (junto al .exe o al .py)
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(BASE_DIR, "productos.json")
COUNTER_PATH = os.path.join(BASE_DIR, "contador.json")   # ultimo numero de codigo usado (nunca se reutiliza)
CODE_PREFIX = "NX-"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
UA_MOBILE = ("Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/124.0 Mobile Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "es-AR,es;q=0.9", "Accept": "text/html,*/*"}
HEADERS_MOBILE = dict(HEADERS, **{"User-Agent": UA_MOBILE})


# ---------------------------------------------------------------- datos
def load_products():
    if not os.path.exists(JSON_PATH):
        return []
    try:
        # utf-8-sig: tolera archivos guardados con BOM (Bloc de notas)
        with open(JSON_PATH, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        # Archivo roto: guardo una copia para no perder lo que habia
        try:
            shutil.copyfile(JSON_PATH, JSON_PATH + ".roto.bak")
        except OSError:
            pass
        return []


LOG_PATH = os.path.join(BASE_DIR, "gestor_log.txt")
# El gestor guarda desde varios hilos (agregar, reparar imágenes, editar): un solo candado
# evita que dos escrituras se pisen y se pierda un producto.
DB_LOCK = threading.RLock()


def log(msg):
    """Registro simple para diagnosticar problemas (gestor_log.txt, junto al programa)."""
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(msg) + "\n")
    except OSError:
        pass


def save_products(products):
    # Escritura atomica: la tienda nunca lee un JSON a medio escribir.
    # En Windows el reemplazo falla si el navegador/servidor tiene el archivo abierto
    # justo en ese instante: se reintenta, y como ultimo recurso se escribe directo.
    tmp = JSON_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    last = None
    for _ in range(10):
        try:
            os.replace(tmp, JSON_PATH)
            return
        except OSError as e:
            last = e
            time.sleep(0.1)
    log(f"os.replace fallo ({last}); escribo directo")
    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(products, f, indent=2, ensure_ascii=False)
    try:
        os.remove(tmp)
    except OSError:
        pass


def _code_num(code):
    m = re.fullmatch(re.escape(CODE_PREFIX) + r"(\d+)", str(code or ""))
    return int(m.group(1)) if m else 0


def next_code(products):
    """Codigo correlativo NX-0001, NX-0002... Se guarda el ultimo numero usado en
    contador.json, asi un codigo de un producto eliminado NO se vuelve a asignar."""
    last = 0
    try:
        with open(COUNTER_PATH, "r", encoding="utf-8") as f:
            last = int(json.load(f).get("ultimo", 0))
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    last = max([last] + [_code_num(p.get("code")) for p in products])
    n = last + 1
    try:
        with open(COUNTER_PATH, "w", encoding="utf-8") as f:
            json.dump({"ultimo": n}, f)
    except OSError as e:
        log(f"no pude guardar contador.json: {e}")
    return f"{CODE_PREFIX}{n:04d}"


def ensure_codes():
    """Les pone codigo a los productos que no tienen (los cargados antes de esta version),
    en el orden en que estan en la lista. Devuelve cuantos codigos asigno."""
    with DB_LOCK:
        products = load_products()
        nuevos = 0
        for p in products:
            if not p.get("code"):
                p["code"] = next_code(products)
                nuevos += 1
        if nuevos:
            save_products(products)
        return nuevos


def next_id(products):
    ids = [p["id"] for p in products if isinstance(p.get("id"), int)]
    return (max(ids) + 1) if ids else 1


# ------------------------------------------------------------ extracción
def find_ml_id(text):
    m = re.search(r"(?<![A-Za-z])(ML[A-Z]U?)[-_]?(\d{6,})\b", text or "", re.I)
    return f"{m.group(1).upper()}{m.group(2)}" if m else None


def parse_price(txt):
    """Convierte '1299.50', '1.299,50', '45.999' o '45,999.50' en float (None si no se puede)."""
    t = re.sub(r"[^\d.,]", "", str(txt or ""))
    if not t:
        return None
    if "," in t and "." in t:
        # el ultimo separador es el decimal
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".") if len(t.split(",")[-1]) <= 2 else t.replace(",", "")
    elif "." in t:
        # '45.999' = miles (3 decimales exactos); '1299.50' = decimal
        if len(t.split(".")[-1]) == 3 and t.count(".") >= 1:
            t = t.replace(".", "")
    try:
        return float(t)
    except ValueError:
        return None


def _img_urls(img):
    """Devuelve todas las URLs de un campo 'image' de JSON-LD (str, lista, ImageObject)."""
    out = []
    if isinstance(img, str):
        out.append(img)
    elif isinstance(img, dict):
        out.extend(_img_urls(img.get("url") or img.get("contentUrl")))
    elif isinstance(img, list):
        for i in img:
            out.extend(_img_urls(i))
    return out


def ld_product(page):
    """Busca el Product en los bloques JSON-LD (lo que hoy publica Mercado Libre)."""
    found = {"images": []}

    def put(key, val):
        if val and not found.get(key):
            found[key] = val

    for raw in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', page, re.I | re.S):
        try:
            data = json.loads(htmllib.unescape(raw).strip())
        except ValueError:
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                stack.extend(v for v in d.get("@graph", []) if isinstance(v, (dict, list)))
                t = d.get("@type")
                if t == "Product" or (isinstance(t, list) and "Product" in t):
                    put("name", d.get("name"))
                    found["images"].extend(_img_urls(d.get("image")))
                    offers = d.get("offers")
                    if isinstance(offers, list):
                        offers = offers[0] if offers else None
                    if isinstance(offers, dict):
                        put("price", offers.get("price") or offers.get("lowPrice"))
                        put("currency", offers.get("priceCurrency"))
    return found


META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I)
ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*(\"[^\"]*\"|'[^']*')", re.S)
_meta_cache = {"id": None, "tags": []}


def _meta_tags(page):
    """Todas las <meta> de la página como dicts de atributos (se calcula una sola vez por página).
    Se leen tag por tag y solo del principio del HTML: una búsqueda con '.*?' sobre toda la
    página (1-2 MB) puede tardar minutos y congela la ventana."""
    if _meta_cache["id"] is not page:
        tags = []
        for m in META_TAG_RE.finditer(page[:600000]):
            attrs = {k.lower(): v[1:-1] for k, v in ATTR_RE.findall(m.group(0))}
            tags.append(attrs)
        _meta_cache["id"], _meta_cache["tags"] = page, tags
    return _meta_cache["tags"]


def meta(page, key):
    k = key.lower()
    for a in _meta_tags(page):
        if "content" in a and k in (a.get("property", "").lower(), a.get("name", "").lower(),
                                     a.get("itemprop", "").lower()):
            return htmllib.unescape(a["content"]).strip()
    return None


# ---------------------------------------------------------------- imágenes
# Las fotos de productos de Mercado Libre viven en *.mlstatic.com y tienen un id
# del estilo 948273-MLA79581234567_102024 (los logos/íconos no lo tienen).
PIC_KEY_RE = re.compile(r"(\d{5,}-ML[A-Z]U?\d+_\d+)")
MLSTATIC_RE = re.compile(r"https?://[\w.-]*mlstatic\.com/[^\s\"'<>\\)]+?\.(?:jpe?g|png|webp)", re.I)
SIZE_SUFFIX_RE = re.compile(r"-([A-Z])\.(jpe?g|png|webp)$", re.I)


def clean_img_url(u):
    """Normaliza una URL de imagen: https, sin escapes, sin espacios. '' si no sirve."""
    if not u or not isinstance(u, str):
        return ""
    u = htmllib.unescape(u).replace("\\u002F", "/").replace("\\/", "/").strip()
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("http://"):
        u = "https://" + u[7:]
    if not u.startswith("https://") or u.lower().endswith(".svg"):
        return ""
    if re.search(r"logo|sprite|favicon|placeholder|frontend-assets", u, re.I):
        return ""
    return u


def img_key(u):
    m = PIC_KEY_RE.search(u or "")
    return m.group(1) if m else (u or "")


def hd_url(u):
    """Pide la versión grande (-O) de una foto de ML. Si no existe, el llamador usa la original."""
    if "_2X_" in u:
        return u
    return SIZE_SUFFIX_RE.sub(lambda m: "-O." + m.group(2), u)


def page_images(page, ld):
    """(principales, de_respaldo). Principales: JSON-LD + og:image + twitter:image + image_src.
    Respaldo: cualquier foto de mlstatic dentro del HTML (puede incluir productos relacionados,
    por eso solo se usa si no hay principales)."""
    main = list(ld.get("images") or [])
    for key in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src", "image"):
        v = meta(page, key)
        if v:
            main.append(v)
    for m in re.finditer(r"<link\b[^>]*>", page[:600000], re.I):
        a = {k.lower(): v[1:-1] for k, v in ATTR_RE.findall(m.group(0))}
        if a.get("rel", "").lower() == "image_src" and a.get("href"):
            main.append(a["href"])

    def uniq(urls, limit):
        seen, out = set(), []
        for u in urls:
            u = clean_img_url(u)
            k = img_key(u)
            if u and k not in seen:
                seen.add(k)
                out.append(u)
        return out[:limit]

    main = uniq(main, 5)
    fallback = []
    if not main:
        blob = page.replace("\\u002F", "/").replace("\\/", "/")
        fallback = [u for u in uniq(MLSTATIC_RE.findall(blob), 8) if PIC_KEY_RE.search(u)][:3]
    return main, fallback


def parse_page(page):
    """Saca título, imágenes, precio, moneda y categoría del HTML de una publicación."""
    ld = ld_product(page)
    title = ld.get("name") or meta(page, "og:title")
    if not title:
        m = re.search(r"<title[^>]*>(.*?)</title>", page, re.I | re.S)
        title = htmllib.unescape(m.group(1)).strip() if m else None
    if title:
        title = re.sub(r"\s*[|\-–]\s*Mercado\s*Libre.*$", "", title, flags=re.I).strip()

    images, fallback = page_images(page, ld)

    price = ld.get("price") or meta(page, "price") or meta(page, "product:price:amount")
    if not price:
        m = re.search(r'"current_price"\s*:\s*\{\s*"value"\s*:\s*([\d]+(?:\.\d+)?)', page)
        if m:
            price = m.group(1)
    if not price:
        m = re.search(r'<span[^>]*class="[^"]*andes-money-amount[^"]*"[^>]*aria-label="(?:Ahora:\s*)?(\d[\d.]*)\s+pesos', page, re.I)
        if m:
            price = m.group(1).replace('.', '')
    if not price:
        m = re.search(r'"price"\s*:\s*"?(\d+(?:\.\d+)?)', page)
        price = m.group(1) if m else None
    price = parse_price(price)

    currency = ld.get("currency") or meta(page, "priceCurrency")
    if not currency:
        m = re.search(r'"priceCurrency"\s*:\s*"([A-Z]{3})"', page)
        currency = m.group(1) if m else "ARS"

    crumbs = [htmllib.unescape(c).strip() for c in
              re.findall(r'class="andes-breadcrumb__link"[^>]*>([^<]+)<', page)]
    crumbs = [c for c in crumbs if c and not c.lower().startswith("volver")]
    category = crumbs[0] if crumbs else None

    return {"name": title, "image": (images or fallback or [""])[0],
            "images": images or fallback, "price": price,
            "currency": currency or "ARS", "category": category}


def fetch_from_api(ml_id):
    token = os.environ.get("ML_ACCESS_TOKEN")
    if not token:
        tp = os.path.join(BASE_DIR, "token.txt")
        if os.path.exists(tp):
            token = open(tp, encoding="utf-8").read().strip()
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = requests.get(f"https://api.mercadolibre.com/items/{ml_id}", headers=h, timeout=(5, 6))
    if r.status_code != 200:
        return None
    d = r.json()
    pics = d.get("pictures") or []
    category = None
    if d.get("category_id"):
        c = requests.get(f"https://api.mercadolibre.com/categories/{d['category_id']}", headers=h, timeout=(5, 6))
        if c.status_code == 200:
            cj = c.json()
            root = (cj.get("path_from_root") or [{}])[0]
            category = root.get("name") or cj.get("name")   # la raiz, no la subcategoria hoja
    urls = [clean_img_url(x.get("secure_url") or x.get("url")) for x in pics]
    urls = [u for u in urls if u] or [clean_img_url(d.get("thumbnail"))]
    urls = [u for u in urls if u]
    return {"name": d.get("title"),
            "image": urls[0] if urls else "", "images": urls[:5],
            "price": d.get("price"), "currency": d.get("currency_id") or "ARS",
            "category": category}


TOTAL_BUDGET = 12   # segundos maximos para leer la pagina de la publicacion
IMAGE_BUDGET = 6    # segundos maximos (en total) para comprobar las fotos
MAX_BYTES = 2_000_000


class _Resp:
    def __init__(self, url, status, text, chain=None):
        self.url, self.status_code, self.text = url, status, text
        self.chain = chain or [url]     # todas las URLs por las que pasó (redirecciones)


def _download(url, box, headers=None):
    try:
        r = requests.get(url, headers=headers or HEADERS, timeout=(5, 8), allow_redirects=True)
        raw = r.content[:MAX_BYTES]
        # Decodificacion directa: evita que requests "adivine" el idioma (lento en paginas grandes)
        enc = r.encoding if r.encoding and r.encoding.lower() != "iso-8859-1" else "utf-8"
        box["r"] = _Resp(r.url, r.status_code, raw.decode(enc, errors="replace"),
                         [h.url for h in r.history] + [r.url])
    except Exception as e:  # se informa al hilo principal
        box["e"] = e


def http_get(url, deadline, headers=None):
    """GET con tope de tiempo TOTAL (el timeout de requests solo limita cada espera,
    un sitio que gotea datos lo puede colgar para siempre)."""
    left = deadline - time.monotonic()
    if left <= 1:
        raise requests.Timeout("sin tiempo")
    box = {}
    th = threading.Thread(target=_download, args=(url, box, headers), daemon=True)
    th.start()
    th.join(left)
    if "r" in box:
        return box["r"]
    if "e" in box and isinstance(box["e"], requests.RequestException):
        raise box["e"]
    raise requests.Timeout("la publicacion tardo demasiado")


GENERIC = {"", "mercado libre", "mercadolibre", "mercado libre argentina", "mercado libre - envios gratis",
           "mercado libre - envíos gratis"}
BLOCKED_HINTS = ("ingresá a tu cuenta", "ingresa a tu cuenta", "verificando", "verifying",
                 "just a moment", "access denied", "captcha", "forbidden")


def valid_name(data):
    if not (data and data.get("name")):
        return False
    if _name_dead(data["name"]):
        return False
    n = data["name"].strip().lower()
    return n not in GENERIC and not any(h in n for h in BLOCKED_HINTS)


def product_links(page):
    pat = (r'https?://(?:articulo|www|produto|listado)\.mercadolibre\.com\.ar/[^"\'\s<>\\]*'
           r'ML[A-Z]-?\d{6,}[^"\'\s<>\\]*')
    seen, out = set(), []
    for m in re.findall(pat, page):
        m = htmllib.unescape(m).replace("\\u002F", "/")
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out[:3]


def check_image(url, deadline=None):
    """True = la imagen existe; False = no existe / no es imagen; None = no se pudo comprobar."""
    try:
        r = requests.get(url, headers=dict(HEADERS, Accept="image/*,*/*"), timeout=(3, 3),
                         stream=True, allow_redirects=True)
        ok = r.status_code == 200 and r.headers.get("Content-Type", "").lower().startswith("image/")
        r.close()
        return ok
    except requests.RequestException:
        return None


def pick_images(data, deadline=None):
    """Elige la imagen principal que realmente carga (probando primero la versión HD)
    y deja en data['image'] / data['images'] las URLs finales.
    Todas las comprobaciones corren a la vez y el total nunca pasa de IMAGE_BUDGET segundos."""
    cands = [u for u in ([data.get("image")] + list(data.get("images") or [])) if u]
    ordered = list(dict.fromkeys(cands))
    variants = []
    for u in ordered[:2]:
        variants.extend(dict.fromkeys([hd_url(u), u]))
    variants = list(dict.fromkeys(variants))
    results = {}

    def run(v):
        results[v] = check_image(v)

    threads = [threading.Thread(target=run, args=(v,), daemon=True) for v in variants]
    for t in threads:
        t.start()
    end = time.monotonic() + IMAGE_BUDGET
    for t in threads:
        t.join(max(0.0, end - time.monotonic()))

    main = next((v for v in variants if results.get(v) is True), "")
    if not main:
        # Ninguna confirmada: si no pude comprobar (red lenta) la guardo igual; si todas dieron
        # "no existe", queda vacía para reintentar luego.
        main = next((u for u in ordered if results.get(u) is None), "")
    rest = [hd_url(u) for u in ordered if img_key(u) != img_key(main)][:4]
    data["image"] = main
    data["images"] = [main] + rest if main else []
    return data


def _merge(base, extra):
    """Completa los huecos de base con lo que trae extra (nombre, precio, imágenes...)."""
    if not extra:
        return base
    if not base:
        return dict(extra)
    for k in ("name", "price", "category"):
        if not base.get(k) and extra.get(k):
            base[k] = extra[k]
    if not base.get("image") and extra.get("image"):
        base["image"], base["images"] = extra["image"], extra.get("images") or [extra["image"]]
    if not base.get("currency"):
        base["currency"] = extra.get("currency") or "ARS"
    return base


def fetch_product(url):
    """Devuelve (datos, ml_id). datos es None si no se pudo leer.
    Si la página no trae foto, se prueba con otro navegador simulado, con la API y con
    la página interna del enlace, y recién después se da por perdida la imagen."""
    ml_id = find_ml_id(url)
    data = None
    deadline = time.monotonic() + TOTAL_BUDGET
    visited = set()

    def read(u, headers, once=False):
        """Lee una página: (datos, enlaces_a_productos) o None. Actualiza ml_id si la página lo revela."""
        nonlocal ml_id
        if once and u in visited:
            return None
        visited.add(u)
        r = http_get(u, deadline, headers)
        ml_id = find_ml_id(r.url) or find_ml_id(r.text[:200000]) or ml_id
        if r.status_code != 200:
            return None
        return parse_page(r.text), product_links(r.text)

    # 1º navegador de escritorio, 2º navegador móvil (a veces ML responde distinto)
    for headers in (HEADERS, HEADERS_MOBILE):
        if data and data.get("image"):
            break
        try:
            res = read(url, headers)
        except requests.RequestException:
            continue
        if not res or not res[0]:
            continue
        d, links = res
        if valid_name(d):
            data = _merge(data, d)
            continue
        # Enlaces cortos (meli.la) o páginas intermedias: busco el enlace del producto adentro.
        for link in links:
            try:
                r2 = read(link, headers, once=True)
            except requests.RequestException:
                break
            if r2 and r2[0] and valid_name(r2[0]):
                data = _merge(data, r2[0])
                ml_id = find_ml_id(link) or ml_id
                break

    # Sin nombre o sin foto: pruebo la API oficial (usa token.txt si existe).
    if (not valid_name(data) or not data.get("image")) and ml_id and time.monotonic() < deadline:
        try:
            api = fetch_from_api(ml_id)
            if api and valid_name(api):
                data = _merge(data, api)
        except (requests.RequestException, ValueError):
            pass

    if not valid_name(data):
        return None, ml_id
    pick_images(data)    # comprobar la foto tiene su propio tope (IMAGE_BUDGET)
    return data, ml_id


def is_affiliate(url):
    """True si parece un enlace de afiliado de Mercado Libre (meli.la, /social/ o matt_*)."""
    try:
        sp = urlsplit(url or "")
    except ValueError:
        return False
    return sp.netloc.lower().endswith("meli.la") or "/social/" in sp.path or "matt_" in sp.query


def name_from_url(url):
    """Nombre aproximado desde el texto de la URL (para precargar la carga manual)."""
    try:
        path = unquote(urlsplit(url).path)
    except ValueError:
        return ""
    m = re.search(r"ML[A-Z]-?\d{6,}-(.+?)(?:-_JM|_JM|$)", path, re.I)
    if not m:
        m = re.search(r"/([a-z0-9-]{12,})/p/ML[A-Z]\d+", path, re.I)
    if not m:
        return ""
    return re.sub(r"[-_]+", " ", m.group(1)).strip().capitalize()


# Categorias principales de Mercado Libre Argentina
CATEGORIES = [
    "Accesorios para Vehículos", "Agro", "Alimentos y Bebidas", "Animales y Mascotas",
    "Antigüedades y Colecciones", "Arte, Librería y Mercería", "Bebés",
    "Belleza y Cuidado Personal", "Cámaras y Accesorios", "Celulares y Teléfonos",
    "Computación", "Consolas y Videojuegos", "Construcción",
    "Deportes y Fitness", "Electrodomésticos y Aires Ac.", "Electrónica, Audio y Video",
    "Herramientas", "Hogar, Muebles y Jardín", "Industrias y Oficinas",
    "Instrumentos Musicales", "Joyas y Relojes", "Juegos y Juguetes",
    "Libros, Revistas y Comics", "Música, Películas y Series", "Ropa y Accesorios",
    "Salud y Equipamiento Médico", "Souvenirs, Cotillón y Fiestas", "Otros",
]

# Palabras clave para adivinar la categoria cuando la publicacion no la trae
KEYWORDS = {
    "Celulares y Teléfonos": ["celular", "smartphone", "iphone", "samsung galaxy", "galaxy a", "moto g", "moto e", "motorola", "redmi note", "telefono", "teléfono"],
    "Computación": ["notebook", "laptop", "pc", "monitor", "teclado", "mouse", "impresora", "ssd", "disco rigido", "disco solido", "memoria ram", "router", "tablet", "ipad", "starlink", "cargador notebook", "cargador para notebook", "webcam", "pendrive"],
    "Consolas y Videojuegos": ["playstation", "ps5", "ps4", "xbox", "nintendo", "joystick", "gamer", "videojuego", "control ps5", "control xbox"],
    "Electrónica, Audio y Video": ["auricular", "parlante", "smart tv", "televisor", "tv", "bluetooth", "soundbar", "cargador", "camara de seguridad"],
    "Cámaras y Accesorios": ["camara", "cámara", "gopro", "lente", "tripode", "trípode", "drone"],
    "Electrodomésticos y Aires Ac.": ["heladera", "lavarropas", "microondas", "aire acondicionado", "cafetera", "freidora", "sandwichera", "yogurtera", "maquina de soda", "hidrolavadora", "mixer", "aspiradora", "licuadora", "batidora", "horno", "pava electrica", "ventilador"],
    "Hogar, Muebles y Jardín": ["mesa ratona", "caja organizadora", "cubiertos", "canasto parrillero", "mopa", "vanitory", "espejo", "escalera", "desmalezadora", "mesa de luz", "sillon", "sillón", "mesa", "silla", "cama", "colchon", "colchón", "placard", "sabana", "sábana", "cortina", "alfombra", "jardin", "jardín", "maceta", "lampara", "lámpara"],
    "Herramientas": ["bomba presurizadora", "taladro", "amoladora", "destornillador", "atornillador", "soldadora", "llave", "herramienta", "sierra"],
    "Construcción": ["cemento", "pintura", "ceramica", "cerámica", "porcelanato", "grifo", "sanitario", "caño"],
    "Ropa y Accesorios": ["zapatilla", "chaleco", "jogger", "remera", "campera", "jean", "pantalon", "pantalón", "vestido", "camisa", "buzo", "mochila", "billetera", "zapato", "bota", "short", "calza", "ojotas", "medias"],
    "Deportes y Fitness": ["bicicleta", "monopatin", "monopatín", "cinta caminadora", "cinta motorizada", "discos para mancuerna", "pesa", "mancuerna", "yoga", "futbol", "fútbol", "pelota", "cinta de correr", "proteina", "proteína", "camping", "carpa"],
    "Belleza y Cuidado Personal": ["perfume", "eau de parfum", "serum", "sérum", "depiladora", "buclera", "rizador", "modelador", "mascara de pestañas", "oleo", "óleo", "gel limpiador", "shampoo", "crema", "maquillaje", "labial", "secador", "planchita", "afeitadora", "cuidado facial"],
    "Bebés": ["bebe", "bebé", "pañal", "cochecito", "cuna", "mamadera"],
    "Juegos y Juguetes": ["juguete", "lego", "muñeca", "rompecabezas", "peluche", "didactico", "didáctico"],
    "Animales y Mascotas": ["perro", "gato", "mascota", "alimento balanceado", "arnes", "arnés"],
    "Accesorios para Vehículos": ["auto", "moto", "neumatico", "neumático", "aceite motor", "bateria de auto", "cubierta", "casco"],
    "Libros, Revistas y Comics": ["libro", "novela", "comic", "manga"],
    "Instrumentos Musicales": ["guitarra", "bajo electrico", "piano", "bateria electronica", "ukelele", "microfono", "micrófono"],
    "Joyas y Relojes": ["reloj", "anillo", "cadena", "pulsera", "collar", "aros", "dije"],
    "Salud y Equipamiento Médico": ["masajeador", "tiras reactivas", "magnesio", "colageno", "colágeno", "tensiometro", "tensiómetro", "termometro", "termómetro", "ortopedic", "ortopédic", "barbijo", "oximetro", "oxímetro"],
    "Alimentos y Bebidas": ["yerba", "cafe en grano", "café", "vino", "cerveza", "snack", "alfajor"],
    "Industrias y Oficinas": ["contadora de billetes", "plancha estampadora", "sublimadora", "oficina", "impresora termica", "etiquetas", "balanza comercial", "escritorio"],
}


def _norm(t):
    import unicodedata
    t = unicodedata.normalize("NFD", (t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# Nombres con los que Mercado Libre llama a sus rubros y que no coinciden con la lista de arriba
ALIASES = {
    "hogar y muebles": "Hogar, Muebles y Jardín", "hogar": "Hogar, Muebles y Jardín",
    "muebles": "Hogar, Muebles y Jardín", "jardin": "Hogar, Muebles y Jardín",
    "casa, muebles y jardin": "Hogar, Muebles y Jardín",
    "celulares": "Celulares y Teléfonos", "telefonos": "Celulares y Teléfonos",
    "electrodomesticos": "Electrodomésticos y Aires Ac.", "aires acondicionados": "Electrodomésticos y Aires Ac.",
    "electronica": "Electrónica, Audio y Video", "audio": "Electrónica, Audio y Video",
    "tv, audio y video": "Electrónica, Audio y Video",
    "videojuegos": "Consolas y Videojuegos", "consolas": "Consolas y Videojuegos",
    "herramientas y construccion": "Herramientas",
    "deportes": "Deportes y Fitness", "fitness": "Deportes y Fitness",
    "ropa": "Ropa y Accesorios", "ropa y calzado": "Ropa y Accesorios",
    "indumentaria": "Ropa y Accesorios", "calzado": "Ropa y Accesorios",
    "belleza": "Belleza y Cuidado Personal", "salud": "Salud y Equipamiento Médico",
    "juegos y juguetes": "Juegos y Juguetes", "juguetes": "Juegos y Juguetes",
    "mascotas": "Animales y Mascotas", "animales": "Animales y Mascotas",
    "vehiculos": "Accesorios para Vehículos", "autos, motos y otros": "Accesorios para Vehículos",
    "accesorios para autos y camionetas": "Accesorios para Vehículos",
    "accesorios para motos y cuatriciclos": "Accesorios para Vehículos",
    "camaras": "Cámaras y Accesorios", "joyas": "Joyas y Relojes", "relojes": "Joyas y Relojes",
    "libros": "Libros, Revistas y Comics", "instrumentos": "Instrumentos Musicales",
    "musica": "Música, Películas y Series", "industrias": "Industrias y Oficinas",
    "souvenirs": "Souvenirs, Cotillón y Fiestas", "otras categorias": "Otros",
}


def normalize_category(cat):
    """Devuelve el nombre oficial de la lista si la categoria leida coincide (exacto o por alias).
    Si no la reconoce devuelve None (antes se guardaba tal cual y aparecian categorias raras o duplicadas)."""
    c = _norm(cat).strip()
    if not c:
        return None
    for official in CATEGORIES:
        if c == _norm(official):
            return official
    if c in ALIASES:
        return ALIASES[c]
    for official in CATEGORIES:   # coincide con una de las partes: "Celulares y Teléfonos" -> "Celulares"
        if c in [_norm(x).strip() for x in official.replace(" y ", ", ").split(", ")]:
            return official
    return None


_KW_CACHE = {}


def _kw_regex(word):
    """La palabra clave tiene que ser una palabra entera (admite plural): 'cama' ya no matchea 'cámara'."""
    if word not in _KW_CACHE:
        w = re.escape(_norm(word).strip())
        _KW_CACHE[word] = re.compile(r"(?<![a-z0-9])" + w + r"(?:s|es)?(?![a-z0-9])")
    return _KW_CACHE[word]


def guess_category(name):
    """Adivina la categoria por el titulo. Cuenta palabras enteras; las frases largas y las que
    aparecen al principio del titulo (donde ML pone el producto) pesan mas."""
    n = _norm(name)
    if not n.strip():
        return None
    n = re.sub(r"\bmoto ([ge])\d+", r"motorola celular", n)   # "Moto G47" es un celular, no una moto
    best, best_key = None, (0, 0)
    for cat, words in KEYWORDS.items():
        score, first = 0, 10 ** 6
        for w in words:
            m = _kw_regex(w).search(n)
            if not m:
                continue
            score += len(w.split()) * (2 if m.start() < 25 else 1)
            first = min(first, m.start())
        if score and (score, -first) > best_key:
            best, best_key = cat, (score, -first)
    return best


def all_categories(products):
    existing = {p.get("category") for p in products if p.get("category")}
    return sorted(set(CATEGORIES) | existing, key=lambda c: (c == "Otros", _norm(c)))


def registrar_precio(q, nuevo):
    """Guarda el precio nuevo. Si bajó, deja el anterior y la fecha para el cartel "Bajó de precio"."""
    viejo = q.get("price")
    try:
        if viejo is not None and nuevo is not None and float(nuevo) < float(viejo):
            q["prev_price"] = viejo
            q["price_drop"] = time.strftime("%Y-%m-%d")
        elif viejo is not None and nuevo is not None and float(nuevo) > float(viejo):
            q.pop("prev_price", None)    # subió: ya no es una baja
            q.pop("price_drop", None)
    except (TypeError, ValueError):
        pass
    q["price"] = nuevo


def build_entry(products, data, ml_id, link, category_override=None, source=None):
    image = data.get("image") or ""
    return {
        "id": next_id(products),
        "code": next_code(products),
        "ml_id": ml_id,
        "name": re.sub(r"\s+-\s+\$\s?[\d.,]+\s*$", "", data["name"]).strip(),   # ML a veces pega " - $ precio"
        "category": (category_override
                     or normalize_category(data.get("category"))
                     or guess_category(data.get("name"))
                     or (data.get("category") or "").strip()
                     or "Otros"),
        "price": data.get("price"),
        "currency": data.get("currency") or "ARS",
        "image": image,
        "images": (data.get("images") or [image]) if image else [],
        "link": link,
        "source": source or link,   # enlace original: sirve para reintentar la imagen
        "status": "disponible",     # disponible | no_disponible | dudoso (lo actualiza "Verificar enlaces")
        "checked": None,            # fecha/hora del ultimo chequeo
        "added": time.strftime("%Y-%m-%d"),   # para la sección "Novedades" de la tienda
    }


# ------------------------------------------------------ verificar enlaces
# Textos que Mercado Libre muestra cuando una publicacion ya no se puede comprar.
DEAD_HINTS = ("publicación finalizada", "publicacion finalizada", "publicación pausada",
              "publicacion pausada", "esta publicación no está disponible",
              "esta publicacion no esta disponible", "la publicación que buscás no existe",
              "la publicacion que buscas no existe", "ya no está disponible",
              "ya no esta disponible", "no hay stock", "sin stock disponible",
              "página no encontrada", "pagina no encontrada",
              )
# Solo para páginas /social/ (enlace de afiliado cuyo producto ya no existe):
EMPTY_PROFILE_HINTS = ("este perfil está vacío", "este perfil esta vacio")
DEAD_LD = ("outofstock", "soldout", "discontinued")


_UNI_RE = re.compile(r"\\u([0-9a-fA-F]{4})")


DEAD_NAMES = ("perfil social",)   # asi se llama la pagina a la que cae un enlace sin producto


def _name_dead(name):
    """True si el nombre/título es el de la página de perfil social (enlace sin producto)."""
    n = _norm(name).strip()
    return any(d in n for d in DEAD_NAMES)


def _title_dead(page):
    head = page[:600000]
    titles = [m.group(1) for m in re.finditer(r"<title[^>]*>(.*?)</title>", head, re.I | re.S)]
    og = meta(page, "og:title")
    if og:
        titles.append(og)
    return any(_name_dead(htmllib.unescape(t)) for t in titles)


def _visible(page):
    """HTML sin <script> ni <style>. Las frases tipo "no hay stock" o "publicación finalizada"
    viven en los textos internos (JavaScript) de TODAS las páginas de ML, también las de
    productos disponibles: solo valen si las ve el comprador."""
    head = page[:600000]
    low = head.lower()
    out, i = [], 0
    while True:
        cands = [x for x in (low.find("<script", i), low.find("<style", i)) if x != -1]
        if not cands:
            out.append(head[i:])
            break
        a = min(cands)
        out.append(head[i:a])
        cierre = "</script>" if low.startswith("<script", a) else "</style>"
        b = low.find(cierre, a)
        if b == -1:
            break
        i = b + len(cierre)
    return " ".join(out)


def _ld_unavailable(page):
    for m in re.findall(r'"availability"\s*:\s*"([^"]+)"', page[:600000]):
        if any(x in m.lower() for x in DEAD_LD):
            return True
    return False


def _visible_low(page):
    low = _visible(page).lower()
    return htmllib.unescape(_UNI_RE.sub(lambda m: chr(int(m.group(1), 16)), low))


def _page_dead(page):
    """True si la pagina dice (de forma visible o en sus datos estructurados) que la
    publicacion esta finalizada/pausada/sin stock. Si la pagina muestra el producto con
    precio y a la venta, NO esta caida aunque aparezca alguna frase suelta."""
    if _ld_unavailable(page):
        return True
    ld = ld_product(page)
    if ld.get("name") and ld.get("price") and not _name_dead(ld["name"]):
        return False
    low = _visible_low(page)
    return any(h in low for h in DEAD_HINTS)


def _item_in_page(text, ml_id):
    num = re.sub(r"\D", "", ml_id or "")
    return bool(num) and num in text[:600000]


def _resp_dead(r, ml_id=None):
    """True SOLO si hay evidencia concreta de que el producto ya no se puede comprar.
    Ante la duda devuelve False (el producto queda 'dudoso' y NO se elimina).
    IMPORTANTE: los enlaces de afiliado de ML (meli.la) terminan SIEMPRE en una pagina
    /social/... Eso es lo normal, NO significa que el producto este caido. En esas paginas
    solo se considera caido si dicen de forma visible que el perfil esta vacio."""
    page = r.text or ""
    if _is_lists_url(r.url):    # cae en /social/<usuario>/lists = perfil sin producto = caído
        return True
    if _is_social_url(r.url):
        if _item_in_page(page, ml_id):          # el producto esta en esa pagina: sigue vivo
            return _page_dead(page)
        return any(h in _visible_low(page) for h in EMPTY_PROFILE_HINTS)
    return _page_dead(page)


DEFINITIVE_DEAD = set()   # ids que cayeron en /social/<usuario>/lists: caído seguro, el freno no los toca


def _is_lists_url(final_url):
    """True si la URL final es https://www.mercadolibre.com.ar/social/<usuario>/lists
    (la página del perfil vacío): el enlace está caído."""
    try:
        path = urlsplit(final_url or "").path.lower().rstrip("/")
    except ValueError:
        return False
    return re.fullmatch(r"/social/[^/]+/lists", path) is not None


def _is_social_url(final_url):
    """True si la URL es una pagina /social/... (donde caen los enlaces de afiliado).
    Es informativo: por si solo NO indica que el producto este caido."""
    try:
        path = urlsplit(final_url or "").path.lower()
    except ValueError:
        return False
    return "/social/" in path


def _affiliate_dead(url, ml_id=None):
    """True = el enlace de afiliado cae en una página vacía/inexistente; False = anda;
    None = no se pudo comprobar (bloqueo o sin internet)."""
    if not url:
        return None
    resultado = None
    for headers in (HEADERS, HEADERS_MOBILE):
        try:
            r = http_get(url, time.monotonic() + 12, headers)
        except requests.RequestException:
            continue
        if _is_lists_url(r.url):
            return "lists"
        if r.status_code in (404, 410) or (r.status_code == 200 and _resp_dead(r, ml_id)):
            return True
        if r.status_code == 200:
            resultado = False
            break
    return resultado


def diagnose_product(p):
    """Texto con lo que Mercado Libre devuelve para los enlaces de un producto (para ajustar la detección)."""
    out = [f"=== {p.get('code', '')} {p.get('name', '')[:60]}"]
    vistos = []
    for etiqueta, u in (("enlace original", p.get("source")), ("enlace de afiliado", p.get("link"))):
        if not u or u in vistos:
            continue
        vistos.append(u)
        out.append(f"[{etiqueta}] {u}")
        for nombre, headers in (("PC", HEADERS), ("móvil", HEADERS_MOBILE)):
            try:
                r = http_get(u, time.monotonic() + 15, headers)
            except requests.RequestException as e:
                out.append(f"  ({nombre}) ERROR: {e}")
                continue
            low = _UNI_RE.sub(lambda m: chr(int(m.group(1), 16)), r.text.lower())
            t = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.I | re.S)
            out.append(f"  ({nombre}) estado HTTP {r.status_code}, {len(r.text)} caracteres")
            out.append(f"  ({nombre}) camino: " + "  ->  ".join(r.chain))
            out.append(f"  ({nombre}) título: {htmllib.unescape(t.group(1)).strip()[:100] if t else '(sin título)'}")
            out.append(f"  ({nombre}) ¿se detecta como caído?: {'SÍ' if _resp_dead(r, p.get('ml_id')) else 'NO'}")
            for kw in ("perfil", "vacío", "vacio", "no está disponible", "finalizada", "pausada"):
                i = low.find(kw)
                if i >= 0:
                    out.append(f"  ({nombre}) aparece «{kw}»: …{low[max(0, i - 50):i + 70]!r}…")
            if not r.text.strip():
                out.append(f"  ({nombre}) página vacía")
    return "\n".join(out)


def _api_status(ml_id):
    """('disponible'|'no_disponible'|None, precio) segun la API oficial (None = no se pudo)."""
    if not ml_id:
        return None, None
    try:
        token = os.environ.get("ML_ACCESS_TOKEN")
        tp = os.path.join(BASE_DIR, "token.txt")
        if not token and os.path.exists(tp):
            token = open(tp, encoding="utf-8").read().strip()
        h = {"Authorization": f"Bearer {token}"} if token else {}
        r = requests.get(f"https://api.mercadolibre.com/items/{ml_id}", headers=h, timeout=(5, 6))
        if r.status_code != 200:     # 404 incluido: los ids de catalogo (/p/MLA...) no son items
            return None, None
        d = r.json()
        if d.get("status") in ("paused", "closed", "under_review", "inactive") \
                or d.get("available_quantity") == 0:
            return "no_disponible", d.get("price")
        if d.get("status") == "active":
            return "disponible", d.get("price")
    except (requests.RequestException, ValueError):
        pass
    return None, None


def check_product(p):
    """Revisa un producto. Devuelve (estado, precio_nuevo_o_None).
    'dudoso' = no se pudo confirmar (ML bloqueo o no hubo internet): NUNCA se oculta por eso."""
    url = p.get("source") or p.get("link") or ""
    aff = p.get("link") or ""
    ml_id = p.get("ml_id") or find_ml_id(url)
    verdict = None
    price = None
    DEFINITIVE_DEAD.discard(p.get("id"))
    # 0) si el enlace guardado YA es /social/<usuario>/lists: caído seguro, sin consultar nada
    if _is_lists_url(url) or _is_lists_url(aff):
        DEFINITIVE_DEAD.add(p.get("id"))
        return "no_disponible", None
    # 1) la pagina de la publicacion
    for headers in (HEADERS, HEADERS_MOBILE):
        try:
            r = http_get(url, time.monotonic() + 12, headers)
        except requests.RequestException:
            continue
        ml_id = find_ml_id(r.url) or ml_id
        if _is_lists_url(r.url):
            verdict = "no_disponible"
            DEFINITIVE_DEAD.add(p.get("id"))
            break
        if r.status_code in (404, 410):
            verdict = "no_disponible"
            break
        if r.status_code != 200:
            continue
        if _resp_dead(r, ml_id):
            verdict = "no_disponible"
            break
        data = parse_page(r.text)
        if valid_name(data):
            verdict, price = "disponible", data.get("price")
            break
    # 2) si la pagina no alcanzo, la API oficial
    if verdict is None:
        verdict, price = _api_status(ml_id)
    # 3) el enlace de afiliado (lo que abre el botón de la tienda) tambien tiene que andar
    if verdict != "no_disponible" and aff and (aff != url or verdict is None):
        muerto = _affiliate_dead(aff, ml_id)
        if muerto == "lists":
            DEFINITIVE_DEAD.add(p.get("id"))
        if muerto is True or muerto == "lists":
            verdict, price = "no_disponible", None
    return (verdict or "dudoso"), (price if isinstance(price, (int, float)) else None)


def verify_links(only_ids=None, progress=None):
    """Verifica todos los productos (o los de only_ids) y guarda el resultado.
    Devuelve {'disponible': n, 'no_disponible': n, 'dudoso': n}."""
    resumen = {"disponible": 0, "no_disponible": 0, "dudoso": 0, "caidos_ids": [], "precios": []}
    todos = load_products()
    objetivo = [p for p in todos if only_ids is None or p.get("id") in only_ids]
    for n, p in enumerate(objetivo, 1):
        if progress:
            progress(n, len(objetivo), p)
        try:
            estado, precio = check_product(p)
        except Exception as e:   # un producto raro no frena a los demas
            log(f"verify_links fallo en id={p.get('id')}: {e}")
            estado, precio = "dudoso", None
        resumen[estado] += 1
        if estado == "no_disponible" and p.get("id") is not None:
            resumen["caidos_ids"].append(p.get("id"))
        with DB_LOCK:
            fresh = load_products()
            for q in fresh:
                if q.get("id") == p.get("id"):
                    # un "dudoso" no pisa un estado ya confirmado... salvo un "no_disponible"
                    # viejo: ese lo pudo poner la deteccion anterior (con falsos positivos)
                    if estado != "dudoso" or not q.get("status") or q.get("status") == "no_disponible":
                        q["status"] = estado
                    q["checked"] = time.strftime("%Y-%m-%d %H:%M")
                    if estado == "disponible" and precio is not None:
                        anterior = q.get("price")
                        if anterior != precio:
                            resumen["precios"].append((q.get("code", ""), anterior, precio))
                        registrar_precio(q, precio)
                    save_products(fresh)
                    break
    # FRENO: si una parte grande sale "caida" (>=3 y mas del 30%), casi seguro es un bloqueo o una
    # regla equivocada, no productos reales caidos. Se dejan como "dudoso" (siguen visibles).
    # Los que cayeron en /social/<usuario>/lists son caidos SEGUROS: el freno no los toca.
    caidos = set(resumen["caidos_ids"]) - DEFINITIVE_DEAD
    if len(caidos) >= 3 and len(caidos) > len(objetivo) * 0.3:
        with DB_LOCK:
            fresh = load_products()
            for q in fresh:
                if q.get("id") in caidos:
                    q["status"] = "dudoso"
            save_products(fresh)
        log(f"verify_links: {len(caidos)} de {len(objetivo)} salieron caidos; se dejaron como dudosos (freno)")
        resumen["dudoso"] += len(caidos)
        resumen["no_disponible"] -= len(caidos)
        resumen["caidos_ids"] = [i for i in resumen["caidos_ids"] if i in DEFINITIVE_DEAD]
        resumen["masivo"] = len(caidos)
    return resumen


BACKUP_PATH = os.path.join(BASE_DIR, "eliminados_backup.json")


def remove_dead(ids):
    """Elimina de productos.json los productos con esos ids y los guarda en
    eliminados_backup.json (por si hubo un error). Devuelve la lista de eliminados."""
    ids = {i for i in (ids or []) if i is not None}
    if not ids:
        return []
    with DB_LOCK:
        products = load_products()
        # Doble seguro: solo se borra lo que esta marcado "no_disponible". Nunca por id solo.
        caidos = [p for p in products if p.get("id") in ids and p.get("status") == "no_disponible"]
        if not caidos:
            return []
        previo = []
        try:
            with open(BACKUP_PATH, "r", encoding="utf-8") as f:
                previo = json.load(f)
            if not isinstance(previo, list):
                previo = []
        except (OSError, ValueError):
            pass
        sello = time.strftime("%Y-%m-%d %H:%M")
        previo.extend(dict(p, eliminado=sello, motivo="enlace caído") for p in caidos)
        with open(BACKUP_PATH, "w", encoding="utf-8") as f:
            json.dump(previo, f, indent=2, ensure_ascii=False)
        borrar = {p.get("id") for p in caidos}
        save_products([p for p in products if not (p.get("id") in borrar and p.get("status") == "no_disponible")])
        return caidos


def restore_backup():
    """Devuelve a productos.json lo que 'Eliminar caídos' borró (eliminados_backup.json).
    Los repone como 'disponible'; si de verdad están caídos, 'Eliminar caídos' los va a detectar.
    Devuelve cuántos restauró."""
    with DB_LOCK:
        try:
            with open(BACKUP_PATH, "r", encoding="utf-8") as f:
                respaldo = json.load(f)
        except (OSError, ValueError):
            return 0
        if not isinstance(respaldo, list) or not respaldo:
            return 0
        products = load_products()
        claves = {p.get("link") or p.get("ml_id") for p in products} - {None}
        usados = {p.get("id") for p in products}
        n = 0
        for b in respaldo:
            clave = b.get("link") or b.get("ml_id")
            if clave is not None and clave in claves:
                continue
            p = {k: v for k, v in b.items() if k not in ("eliminado", "motivo")}
            if p.get("id") in usados or not isinstance(p.get("id"), int):
                p["id"] = next_id(products)
            p["status"] = "disponible"
            p["checked"] = None
            products.append(p)
            usados.add(p["id"])
            if clave is not None:
                claves.add(clave)
            n += 1
        if n:
            save_products(products)
        shutil.copyfile(BACKUP_PATH, BACKUP_PATH + ".usado.bak")
        with open(BACKUP_PATH, "w", encoding="utf-8") as f:
            json.dump([], f)
        return n


def reset_status(ids=None):
    """Vuelve a 'disponible' los productos marcados como 'no_disponible' (o 'dudoso').
    Es lo que realmente 'restaura' lo que quedo gris en la tienda sin haberse borrado:
    el backup solo guarda lo que 'Eliminar caídos' BORRO, no lo que solo quedo marcado.
    Devuelve cuantos cambio."""
    n = 0
    with DB_LOCK:
        products = load_products()
        for p in products:
            if ids is not None and p.get("id") not in ids:
                continue
            if p.get("status") in ("no_disponible", "dudoso"):
                p["status"] = "disponible"
                p["checked"] = None
                n += 1
        if n:
            save_products(products)
    return n


def revert_mass_down(antes):
    """Freno para 'Actualizar Precios': si en esa pasada una parte grande del catalogo quedo
    'no_disponible', casi seguro es una regla equivocada (los enlaces de afiliado SIEMPRE caen en
    una pagina /social/) y no productos realmente caidos. Se devuelven a su estado anterior.
    'antes' es {id: status} tomado antes de actualizar. Devuelve cuantos revirtio."""
    with DB_LOCK:
        products = load_products()
        nuevos = [p for p in products
                  if p.get("status") == "no_disponible" and p.get("id") in antes
                  and antes[p.get("id")] != "no_disponible"]
        if len(nuevos) >= 2 and len(nuevos) > len(products) * 0.3:
            for p in nuevos:
                p["status"] = antes[p.get("id")] or "disponible"
            save_products(products)
            log(f"revert_mass_down: {len(nuevos)} de {len(products)} salieron caidos al actualizar precios; revertidos")
            return len(nuevos)
    return 0


def reconcile_new_down(antes, progress=None):
    """Despues de 'Actualizar Precios': a los que esa pasada dejo 'no_disponible' los vuelve a
    comprobar con la regla fina (check_product). Si de verdad cae en 'Este perfil esta vacio' (o la
    publicacion no existe) se ELIMINAN (queda respaldo en eliminados_backup.json); si no se puede
    confirmar, vuelven a su estado anterior. Devuelve (eliminados, salvados)."""
    with DB_LOCK:
        products = load_products()
    nuevos = [p for p in products
              if p.get("status") == "no_disponible" and p.get("id") in antes
              and antes[p.get("id")] != "no_disponible"]
    confirmados, salvados = [], 0
    for n, p in enumerate(nuevos, 1):
        if progress:
            progress(n, len(nuevos), p)
        try:
            estado, _precio = check_product(p)
        except Exception as e:
            log(f"reconcile_new_down fallo en id={p.get('id')}: {e}")
            estado = "dudoso"
        if estado == "no_disponible":
            confirmados.append(p.get("id"))
        else:
            with DB_LOCK:
                fresh = load_products()
                for q in fresh:
                    if q.get("id") == p.get("id"):
                        q["status"] = antes[p.get("id")] or "disponible"
                        break
                save_products(fresh)
            salvados += 1
    borrados = remove_dead(confirmados)
    return len(borrados), salvados


def repair_images(only_ids=None):
    """Busca la imagen de los productos que quedaron sin foto. Devuelve cuántos arregló."""
    fixed = 0
    for p in [q for q in load_products() if not q.get("image")]:
        if only_ids is not None and p.get("id") not in only_ids:
            continue
        try:
            data, ml_id = fetch_product(p.get("source") or p.get("link") or "")
        except Exception as e:  # una publicación rota no frena a las demás
            log(f"repair_images fallo en id={p.get('id')}: {e}")
            continue
        if not (data and data.get("image")):
            continue
        with DB_LOCK:
            products = load_products()
            for q in products:
                if q.get("id") == p.get("id") and not q.get("image"):
                    q["image"] = data["image"]
                    q["images"] = data.get("images") or [data["image"]]
                    if q.get("price") is None and data.get("price") is not None:
                        q["price"] = data["price"]
                    if ml_id and not q.get("ml_id"):
                        q["ml_id"] = ml_id
                    save_products(products)
                    fixed += 1
                    break
    return fixed


# ------------------------------------------------------- publicar online
SITE_DIR = os.path.join(BASE_DIR, "sitio")
# lo unico que va online (los que no existan se saltean)
SITE_FILES = ("index.html", "favicon.ico", "favicon.png", "favicon.svg", "og.jpg", "logo.jpg", "CNAME")


def build_site():
    """Copia a la carpeta 'sitio' solo lo que la tienda necesita (nunca el .py, logs ni contadores)
    y genera una página por producto + sitemap.xml + robots.txt (ver generar_paginas.py)."""
    os.makedirs(SITE_DIR, exist_ok=True)
    for name in SITE_FILES:
        src = os.path.join(BASE_DIR, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(SITE_DIR, name))
    open(os.path.join(SITE_DIR, ".nojekyll"), "a").close()
    try:
        import generar_paginas
        generar_paginas.generar(SITE_DIR, load_products())
    except Exception as e:      # si falla, se publica igual la tienda (sin páginas de producto)
        log(f"generar_paginas fallo: {e}")
        shutil.copyfile(JSON_PATH, os.path.join(SITE_DIR, "productos.json"))


def _git(*args):
    import subprocess
    kw = {"creationflags": 0x08000000} if os.name == "nt" else {}   # sin ventana de consola
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    try:
        return subprocess.run(["git", *args], cwd=SITE_DIR, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=120, env=env, **kw)
    except FileNotFoundError:
        raise RuntimeError("No encuentro Git en esta PC. Instalalo desde https://git-scm.com "
                           "o subí la carpeta 'sitio' a mano (ver GUIA_PUBLICAR.md).")


def publish_site():
    """Prepara 'sitio'. Si esa carpeta ya es un repositorio de GitHub, sube los cambios.
    Devuelve ('git', mensaje) o ('manual', mensaje). Si algo falla, lanza RuntimeError."""
    build_site()
    if not os.path.isdir(os.path.join(SITE_DIR, ".git")):
        return "manual", ("Armé la carpeta 'sitio' con lo que va online. Arrastrala a la página de Netlify "
                          "que se abrió (o configurá GitHub Pages: ver GUIA_PUBLICAR.md).")
    r = _git("add", "-A")
    if r.returncode != 0:
        raise RuntimeError("git add falló:\n" + (r.stderr or r.stdout).strip())
    r = _git("commit", "-m", "Actualizacion " + time.strftime("%Y-%m-%d %H:%M"))
    salida = (r.stdout + r.stderr).lower()
    if r.returncode != 0 and "nothing to commit" not in salida and "nada para confirmar" not in salida:
        raise RuntimeError("git commit falló:\n" + (r.stderr or r.stdout).strip())
    r = _git("push", "-u", "origin", "HEAD")   # funciona aunque sea el primer push
    if r.returncode != 0:
        raise RuntimeError("No pude subir a GitHub:\n" + (r.stderr or r.stdout).strip())
    return "git", "Publicado. En uno o dos minutos se ve online."


# ------------------------------------------------------- servidor local
_server = {"port": None}

# Solo se publica lo que la tienda necesita (no el .py, ni token.txt, ni .bak)
PUBLIC_PATHS = {"/", "/index.html", "/productos.json", "/favicon.ico", "/favicon.png", "/favicon.svg", "/og.jpg", "/logo.jpg"}


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # En Windows, reuse permitiria "compartir" un puerto ya ocupado por otro
    # servidor (y el navegador terminaria viendo otra carpeta / datos viejos).
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _allowed(self):
        if urlsplit(self.path).path in PUBLIC_PATHS:
            return True
        self.send_error(404)
        return False

    def do_GET(self):
        if self._allowed():
            super().do_GET()

    def do_HEAD(self):
        if self._allowed():
            super().do_HEAD()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def start_server():
    if _server["port"]:
        return _server["port"]
    handler = functools.partial(_Handler, directory=BASE_DIR)
    for port in range(8000, 8021):
        try:
            srv = _Server(("127.0.0.1", port), handler)
        except OSError:
            continue
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        _server["port"] = port
        return port
    return None


# ------------------------------------------------------------------ GUI
def run_gui():
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk

    BG, SURF, LINE = "#0f1316", "#171b1f", "#2a3036"
    TEXT, MUTED, BLUE, MAGENTA = "#f4f6f8", "#98a2ad", "#3a6df0", "#df005b"

    root = tk.Tk()
    root.title("Nexos Market - Gestor de productos [fix social v2]")
    root.geometry("900x680")
    root.minsize(760, 600)
    root.configure(bg=BG)
    ico = os.path.join(BASE_DIR, "favicon.ico")
    if os.path.exists(ico):
        try:
            root.iconbitmap(ico)
        except tk.TclError:
            pass

    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure("Treeview", background=SURF, fieldbackground=SURF, foreground=TEXT,
                    bordercolor=LINE, rowheight=28, borderwidth=0)
    style.configure("Treeview.Heading", background=LINE, foreground=TEXT, relief="flat")
    style.map("Treeview", background=[("selected", BLUE)])
    style.configure("TCombobox", fieldbackground=SURF, background=SURF, foreground=TEXT)

    def label(parent, text, **kw):
        return tk.Label(parent, text=text, bg=BG, fg=kw.pop("fg", TEXT), **kw)

    def button(parent, text, cmd, color=BLUE):
        return tk.Button(parent, text=text, command=cmd, bg=color, fg="white", relief="flat",
                         activebackground=color, activeforeground="white",
                         font=("Segoe UI", 10, "bold"), padx=14, pady=7, cursor="hand2")

    ui_q = queue.Queue()
    last_added = {"id": None}
    store_state = {"opened": False}

    def report_error(exc_type, exc, tb):
        import traceback
        log("ERROR:\n" + "".join(traceback.format_exception(exc_type, exc, tb)))
        set_busy(False)
        status.set(f"Error: {exc}. Detalle en gestor_log.txt")
        try:
            messagebox.showerror("Error", f"Ocurrió un error:\n{exc}\n\nQuedó registrado en gestor_log.txt")
        except Exception:
            pass

    root.report_callback_exception = report_error

    def pump():
        # Un error en una tarea no puede matar el bucle (antes dejaba todo "cargando" para siempre)
        while True:
            try:
                job = ui_q.get_nowait()
            except queue.Empty:
                break
            try:
                job()
            except Exception as e:
                import sys as _s
                report_error(type(e), e, e.__traceback__)
        root.after(100, pump)

    top = tk.Frame(root, bg=BG)
    top.pack(fill="x", padx=18, pady=(16, 6))

    label(top, "Enlace del producto (o directamente el de afiliado)", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, sticky="w")
    url_var = tk.StringVar()
    url_entry = tk.Entry(top, textvariable=url_var, bg=SURF, fg=TEXT, insertbackground=TEXT,
                         relief="flat", font=("Segoe UI", 11), highlightthickness=1,
                         highlightbackground=LINE, highlightcolor=BLUE)
    url_entry.grid(row=1, column=0, sticky="ew", ipady=7, pady=(4, 0))

    def paste():
        try:
            url_var.set(root.clipboard_get().strip())
        except tk.TclError:
            pass

    button(top, "Pegar", paste, "#2a3036").grid(row=1, column=1, padx=(8, 0))

    label(top, "Enlace de AFILIADO (el que cobra comisión: el botón de la tienda usa ESTE)",
          fg=MUTED, font=("Segoe UI", 9)).grid(row=2, column=0, sticky="w", pady=(10, 0))
    aff_var = tk.StringVar()
    tk.Entry(top, textvariable=aff_var, bg=SURF, fg=TEXT, insertbackground=TEXT, relief="flat",
             font=("Segoe UI", 10), highlightthickness=1, highlightbackground=LINE,
             highlightcolor=BLUE).grid(row=3, column=0, columnspan=2, sticky="ew", ipady=5, pady=(4, 0))

    label(top, "Categoría (si la dejás vacía se elige sola)", fg=MUTED, font=("Segoe UI", 9)).grid(row=4, column=0, sticky="w", pady=(10, 0))
    cat_var = tk.StringVar()
    cat_box = ttk.Combobox(top, textvariable=cat_var, font=("Segoe UI", 10))
    cat_box.grid(row=5, column=0, sticky="ew", pady=(4, 0))
    top.columnconfigure(0, weight=1)

    add_btn = button(top, "Agregar producto", lambda: add(), MAGENTA)
    add_btn.grid(row=5, column=1, padx=(8, 0))

    auto_var = tk.BooleanVar(value=True)
    tk.Checkbutton(top, text="Modo automático: copiá el enlace del producto y luego el de afiliado",
                   variable=auto_var, bg=BG, fg=TEXT, selectcolor=SURF, activebackground=BG,
                   activeforeground=TEXT, font=("Segoe UI", 9)
                   ).grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))

    status = tk.StringVar(value="Copiá el enlace del producto y después su enlace de afiliado: se agrega solo. (Si copiás solo el de afiliado, también sirve.)")
    status_lbl = tk.Label(root, textvariable=status, bg=BG, fg=MUTED, anchor="w", font=("Segoe UI", 10))
    status_lbl.pack(fill="x", padx=18, pady=(6, 6))

    # Barra de progreso: aparece mientras hay una tarea larga y se oculta sola al terminar.
    style.configure("Nexos.Horizontal.TProgressbar", troughcolor=SURF, background=BLUE,
                    bordercolor=LINE, lightcolor=BLUE, darkcolor=BLUE, thickness=12)
    prog_frame = tk.Frame(root, bg=BG)
    prog_bar = ttk.Progressbar(prog_frame, style="Nexos.Horizontal.TProgressbar", mode="determinate")
    prog_bar.pack(side="left", fill="x", expand=True)
    prog_pct = tk.Label(prog_frame, text="", bg=BG, fg=TEXT, width=6, anchor="e", font=("Segoe UI", 9, "bold"))
    prog_pct.pack(side="right", padx=(8, 0))
    prog_state = {"jobs": 0}

    def _barra(n=None, total=None):
        if not prog_frame.winfo_ismapped():
            prog_frame.pack(after=status_lbl, fill="x", padx=18, pady=(0, 8))
        if n is None or not total:          # sin total conocido: barra que va y viene
            if prog_bar["mode"] != "indeterminate":
                prog_bar.config(mode="indeterminate")
                prog_bar.start(12)
            prog_pct.config(text="...")
        else:
            if prog_bar["mode"] != "determinate":
                prog_bar.stop()
                prog_bar.config(mode="determinate")
            pct = max(0, min(100, int(n * 100 / total)))
            prog_bar["value"] = pct
            prog_pct.config(text=f"{pct}%")

    def _barra_fin():
        prog_bar.stop()
        prog_bar.config(mode="determinate")
        prog_bar["value"] = 0
        prog_frame.pack_forget()

    def barra(n=None, total=None):
        """Mueve la barra (se puede llamar desde cualquier hilo)."""
        ui_q.put(lambda: _barra(n, total))

    def barra_ini():
        prog_state["jobs"] += 1
        barra()

    def barra_fin():
        def f():
            prog_state["jobs"] = max(0, prog_state["jobs"] - 1)
            if not prog_state["jobs"]:
                _barra_fin()
        ui_q.put(f)

    path_lbl = tk.Label(root, text="Guardando en: " + JSON_PATH, bg=BG, fg=MUTED, anchor="w",
                        font=("Segoe UI", 8))
    path_lbl.pack(side="bottom", fill="x", padx=18, pady=(0, 10))
    bottom = tk.Frame(root, bg=BG)
    bottom.pack(side="bottom", fill="x", padx=18, pady=10)
    verify_row = tk.Frame(root, bg=BG)     # fila de arriba: verificar / eliminar caídos
    verify_row.pack(side="bottom", fill="x", padx=18, pady=(4, 0))

    mid = tk.Frame(root, bg=BG)
    mid.pack(fill="both", expand=True, padx=18)
    cols = ("code", "name", "category", "price", "aff", "estado")
    tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="extended")
    tree.heading("code", text="Código")
    tree.heading("estado", text="Estado")
    tree.heading("name", text="Producto")
    tree.heading("category", text="Categoría")
    tree.heading("price", text="Precio")
    tree.heading("aff", text="Afiliado")
    tree.column("code", width=75, anchor="center")
    tree.column("name", width=300)
    tree.column("category", width=120)
    tree.column("price", width=105, anchor="e")
    tree.column("aff", width=62, anchor="center")
    tree.column("estado", width=105, anchor="center")
    tree.tag_configure("no_disponible", foreground="#ff6b8a")
    tree.tag_configure("dudoso", foreground="#ff6b8a")   # rojo: listos para eliminar (ver «Eliminar caídos»)
    sb = ttk.Scrollbar(mid, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=sb.set)
    tree.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")

    def refresh():
        products = load_products()
        tree.delete(*tree.get_children())
        for i, p in enumerate(products):
            price = p.get("price")
            ptxt = f"{p.get('currency', 'ARS')} {price:,.2f}" if isinstance(price, (int, float)) else "-"
            es_aff = is_affiliate(p.get("link")) or (p.get("source") and p.get("link") != p.get("source"))
            est = p.get("status") or "disponible"
            etxt = {"disponible": "Disponible", "no_disponible": "NO disponible",
                    "dudoso": "Dudoso"}.get(est, est)
            tree.insert("", "end", iid=str(i), tags=(est,),
                        values=(p.get("code", ""), p.get("name", ""), p.get("category", ""), ptxt,
                                "Sí" if es_aff else "NO", etxt))
        cat_box["values"] = all_categories(products)
        caidos = sum(1 for p in products if p.get("status") in ("no_disponible", "dudoso"))
        status.set(f"{len(products)} producto(s) en la tienda."
                   + (f" ⚠ {caidos} en rojo (caídos o dudosos): reemplazalos con «Editar» o tocá «Eliminar caídos»." if caidos else ""))

    def set_busy(busy):
        add_btn.config(state="disabled" if busy else "normal")

    repair_state = {"running": False}

    def auto_repair(manual=False):
        """Reintenta en segundo plano las imágenes que faltan (ML a veces bloquea la 1ª lectura)."""
        if repair_state["running"]:
            return
        repair_state["running"] = True

        def work():
            fixed = 0
            try:
                for intento in range(1 if manual else 3):
                    if not manual:
                        time.sleep(20)
                    fixed += repair_images()
                    if not any(not p.get("image") for p in load_products()):
                        break
            except Exception as e:
                log(f"auto_repair error: {e}")
            finally:
                repair_state["running"] = False

            def done():
                refresh()
                faltan = sum(1 for p in load_products() if not p.get("image"))
                if fixed:
                    status.set(f"Imágenes encontradas: {fixed}. " +
                               (f"Todavía faltan {faltan}." if faltan else "Ya no falta ninguna."))
                elif manual or faltan:
                    status.set(f"No pude obtener imagen de {faltan} producto(s). "
                               "Usá «Editar» y pegá el enlace de la imagen "
                               "(clic derecho sobre la foto > Copiar dirección de imagen).")
            ui_q.put(done)

        threading.Thread(target=work, daemon=True).start()
        if manual:
            status.set("Buscando imágenes que faltan...")

    CONFIG_PATH = os.path.join(BASE_DIR, "gestor_config.json")

    def load_config():
        try:
            if os.path.exists(CONFIG_PATH):
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_config(cfg):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=2)
        except Exception:
            pass

    price_update_state = {"running": False, "cancel_event": None}

    def toggle_actualizar_precios(manual=True):
        """Actualiza precios de todo el catálogo con navegador real (Playwright),
        detectando bajas de precio y dando de baja enlaces caídos o que lleven a perfiles sociales."""
        if price_update_state["running"]:
            if price_update_state["cancel_event"]:
                price_update_state["cancel_event"].set()
                status.set("Deteniendo actualización de precios (se guardará lo avanzado)...")
            return

        if not load_products():
            if manual:
                status.set("No hay productos para actualizar.")
            return

        price_update_state["running"] = True
        barra_ini()
        cancel_evt = threading.Event()
        price_update_state["cancel_event"] = cancel_evt

        update_price_btn.config(text="⏹ Detener", bg="#8a1c3d")
        verify_btn.config(state="disabled")
        purge_btn.config(state="disabled")
        if manual:
            status.set("Iniciando actualizador de precios automático...")

        def on_prog(i, total, p, msg):
            barra(i, total)
            ui_q.put(lambda: status.set(f"Actualizando precios... {i}/{total} ({p.get('code', '')}) - {msg}"))
            if i % 3 == 0 or i == total:
                ui_q.put(refresh)

        def work():
            res = None
            err = None
            antes = {p.get("id"): p.get("status") for p in load_products()}
            try:
                import actualizar_precios
                res = actualizar_precios.actualizar_catalogo(
                    progress_callback=on_prog,
                    cancel_event=cancel_evt,
                    log_callback=log,
                    archivo_json=JSON_PATH
                )
                def prog2(n, total, p):
                    barra(n, total)
                    ui_q.put(lambda: status.set(
                        f"Confirmando perfiles vacíos... {n}/{total} ({p.get('code', '')})"))
                borrados, salvados = reconcile_new_down(antes, prog2)
                if res is not None:
                    res["caidos_social"] = borrados     # eliminados (perfil vacío confirmado)
                    res["revertidos"] = salvados        # no estaban vacíos: siguen disponibles
            except Exception as e:
                err = str(e)
                log(f"actualizar_precios error: {e}")
            finally:
                price_update_state["running"] = False
                price_update_state["cancel_event"] = None
                barra_fin()

            def done():
                update_price_btn.config(text="⚡ Actualizar Precios", bg="#0da9d9")
                verify_btn.config(state="normal")
                purge_btn.config(state="normal")
                refresh()
                if err:
                    status.set(f"Error al actualizar precios: {err[:80]}")
                    if manual:
                        messagebox.showerror("Actualizar precios", f"Error:\n{err}")
                    return
                if res:
                    det = " (detenido)" if res.get("detenido") else ""
                    soc = (f" · {res['caidos_social']} eliminado(s) por perfil vacío "
                           "(tocá «Publicar online»)" if res.get("caidos_social") else "")
                    camb = f" · {res['cambios']} cambio(s) de precio" if res.get("cambios") else ""
                    rev = (f" · {res['revertidos']} no tenían el perfil vacío: siguen disponibles."
                           if res.get("revertidos") else "")
                    status.set(f"Precios actualizados{det}: {res['ok']} listos{camb}{soc}.{rev}")
                    if manual:
                        messagebox.showinfo("Actualización de Precios",
                                            f"Actualización completada:\n\n"
                                            f"• Con precio verificado: {res['ok']}\n"
                                            f"• Cambios de precio: {res['cambios']}\n"
                                            f"• Eliminados (perfil vacío): {res.get('caidos_social', 0)}\n"
                                            f"• Dejados disponibles (no estaban vacíos): {res.get('revertidos', 0)}\n"
                                            f"• Sin precio: {res['sin_precio']}")
            ui_q.put(done)

        threading.Thread(target=work, daemon=True).start()

    verify_state = {"running": False}

    def verify_all(manual=True, only_stale=False):
        """Verifica enlaces en segundo plano. only_stale: solo los no chequeados en 24 h."""
        if verify_state["running"]:
            return
        ids = None
        if only_stale:
            limite = time.strftime("%Y-%m-%d %H:%M", time.localtime(time.time() - 24 * 3600))
            ids = {p.get("id") for p in load_products()
                   if not p.get("checked") or p["checked"] < limite}
            if not ids:
                return
        if not load_products():
            if manual:
                status.set("No hay productos para verificar.")
            return
        verify_state["running"] = True
        barra_ini()
        verify_btn.config(state="disabled")

        def progress(n, total, p):
            barra(n, total)
            ui_q.put(lambda: status.set(f"Verificando enlaces... {n}/{total}  ({p.get('code', '')})"))

        def work():
            res = None
            elim = []
            try:
                res = verify_links(ids, progress)
                # caídos seguros (/social/<usuario>/lists): se eliminan solos (queda respaldo)
                elim = remove_dead([i for i in res["caidos_ids"] if i in DEFINITIVE_DEAD])
            except Exception as e:
                log(f"verify_all error: {e}")
            finally:
                verify_state["running"] = False
                barra_fin()

            def done():
                verify_btn.config(state="normal")
                refresh()
                if res:
                    if elim:
                        res["no_disponible"] -= len(elim)
                    extra = (f" · {len(elim)} eliminado(s) por perfil vacío (tocá «Publicar online»)"
                             if elim else "")
                    extra += f" · {res['dudoso']} dudoso(s) (no pude confirmar, siguen visibles)" if res["dudoso"] else ""
                    pr = f" · {len(res['precios'])} precio(s) corregido(s)" if res["precios"] else ""
                    if res.get("masivo"):
                        status.set(f"⚠ {res['masivo']} salieron 'caídos': es demasiado, no se marcó ninguno "
                                   "(quedan como dudosos). Seleccioná uno y tocá «Diagnóstico».")
                    else:
                        status.set(f"Verificación lista: {res['disponible']} disponible(s), "
                                   f"{res['no_disponible']} caído(s){extra}{pr}.")
            ui_q.put(done)

        threading.Thread(target=work, daemon=True).start()

    def purge_dead():
        """Comprueba TODOS los enlaces y elimina solos los que están caídos."""
        if verify_state["running"]:
            return
        if not load_products():
            status.set("No hay productos para comprobar.")
            return
        verify_state["running"] = True
        barra_ini()
        verify_btn.config(state="disabled")
        purge_btn.config(state="disabled")

        def progress(n, total, p):
            barra(n, total)
            ui_q.put(lambda: status.set(f"Comprobando enlaces... {n}/{total}  ({p.get('code', '')})"))

        def work():
            res = None
            try:
                res = verify_links(None, progress)
            except Exception as e:
                log(f"purge_dead error: {e}")
            finally:
                verify_state["running"] = False
                barra_fin()

            def done():
                verify_btn.config(state="normal")
                purge_btn.config(state="normal")
                if not res:
                    refresh()
                    status.set("No se pudo completar la comprobación. Detalle en gestor_log.txt")
                    return
                caidos = list(dict.fromkeys(res["caidos_ids"]))
                total = len(load_products())
                # Freno de seguridad: si una parte grande aparece caída, probablemente ML me bloqueó.
                sospechosos = [i for i in caidos if i not in DEFINITIVE_DEAD]
                if len(sospechosos) >= 3 and len(sospechosos) > total * 0.3:
                    if not messagebox.askyesno(
                            "Muchos enlaces caídos",
                            f"Salieron {len(caidos)} caídos de {total}. Es MUCHO: puede ser un bloqueo "
                            "temporal de Mercado Libre y no que estén realmente caídos.\n\n"
                            "Recomiendo decir que NO y revisar con «Diagnóstico».\n\n"
                            "¿Eliminarlos igual? (queda un respaldo en eliminados_backup.json)",
                            default="no"):
                        refresh()
                        status.set("No se eliminó nada. Los caídos quedaron marcados en la lista.")
                        return
                borrados = remove_dead(caidos)
                # Los "dudosos" (no pude confirmar) se ven en rojo; se ofrece eliminarlos también.
                dud_ids = [p.get("id") for p in load_products() if p.get("status") == "dudoso"]
                if dud_ids and messagebox.askyesno(
                        "Eliminar dudosos",
                        f"Hay {len(dud_ids)} producto(s) «Dudoso» (en rojo): no pude confirmar si el enlace anda "
                        "(Mercado Libre pudo bloquear la consulta).\n\n"
                        "¿Eliminarlos también?\n(queda un respaldo en eliminados_backup.json y se recuperan "
                        "con «Restaurar eliminados»)", default="no"):
                    with DB_LOCK:
                        fresh = load_products()
                        for q in fresh:
                            if q.get("id") in dud_ids and q.get("status") == "dudoso":
                                q["status"] = "no_disponible"
                        save_products(fresh)
                    borrados = borrados + remove_dead(dud_ids)
                    res["dudoso"] = 0
                refresh()
                dud = f" · {res['dudoso']} dudoso(s) se dejaron (no pude confirmar)" if res["dudoso"] else ""
                np_ = len([x for x in res["precios"] if x[0] not in {p.get("code") for p in borrados}])
                if np_:
                    dud += f" · {np_} precio(s) corregido(s)"
                if borrados:
                    nombres = ", ".join(p.get("code") or p.get("name", "")[:20] for p in borrados[:8])
                    mas = "…" if len(borrados) > 8 else ""
                    status.set(f"Eliminé {len(borrados)} con enlace caído ({nombres}{mas}){dud}. "
                               "Tocá «Publicar online» para actualizar la tienda.")
                else:
                    pista = (" Si alguno debería estar caído, seleccionalo y usá «Diagnóstico»."
                             if res["dudoso"] else "")
                    status.set(f"No encontré enlaces caídos{dud}.{pista}")
            ui_q.put(done)

        threading.Thread(target=work, daemon=True).start()

    def diagnose_selected():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Diagnóstico", "Seleccioná en la lista un producto con enlace caído (hasta 3).")
            return
        prods = load_products()
        elegidos = [prods[int(i)] for i in sel[:3] if int(i) < len(prods)]
        status.set("Diagnosticando... (puede tardar unos segundos)")

        def work():
            try:
                texto = "\n\n".join(diagnose_product(p) for p in elegidos)
            except Exception as e:
                texto = f"Error: {e}"
            log("DIAGNOSTICO\n" + texto)

            def done():
                status.set("Diagnóstico listo.")
                win = tk.Toplevel(root)
                win.title("Diagnóstico de enlaces (copialo con Ctrl+A, Ctrl+C)")
                win.geometry("820x480")
                win.configure(bg=BG)
                box = tk.Text(win, wrap="word", bg=SURF, fg=TEXT, insertbackground=TEXT, relief="flat",
                              font=("Consolas", 9))
                box.pack(fill="both", expand=True, padx=10, pady=10)
                box.insert("1.0", texto)
            ui_q.put(done)

        threading.Thread(target=work, daemon=True).start()

    def finish_add(link, data, ml_id, auto=False, aff=""):
        set_busy(False)
        if data and _name_dead(data.get("name")):
            url_var.set("")
            aff_var.set("")
            status.set("La página leída es un perfil social sin datos de producto: no se agregó.")
            return
        products = load_products()
        if data is None and auto:
            # Modo automatico: no interrumpo ni pierdo el enlace; cargo con lo que haya
            data = {"name": name_from_url(link) or "Producto nuevo (completar con Editar)",
                    "price": None, "currency": "ARS", "image": "", "category": None}
            note = " (sin precio ni imagen: ML bloqueó la lectura; completalo con Editar)"
        else:
            note = ""
        if data is None:
            if messagebox.askyesno(
                    "No pude leer la publicación",
                    "No se pudieron obtener los datos automáticamente.\n\n¿Querés cargarlo a mano?"):
                name = simpledialog.askstring("Nombre", "Nombre del producto:", parent=root,
                                              initialvalue=name_from_url(link))
                if not name:
                    status.set("Carga cancelada.")
                    return
                price_txt = simpledialog.askstring("Precio", "Precio (solo números):", parent=root) or ""
                img = simpledialog.askstring("Imagen", "Enlace de la imagen (opcional):", parent=root) or ""
                price = parse_price(price_txt)
                data = {"name": name, "price": price, "currency": "ARS", "image": img, "category": None}
            else:
                status.set("No se agregó el producto.")
                return
        aff = aff or link      # lo que se abre al tocar el botón de la tienda
        if not is_affiliate(aff) and aff == link:
            note += "  ⚠ SIN enlace de afiliado: no cobrás comisión por este (usá Editar)"
        with DB_LOCK:
            products = load_products()   # se relee dentro del candado: no pisa cambios recientes
            if any((ml_id and p.get("ml_id") == ml_id) or link in (p.get("link"), p.get("source"))
                   for p in products):
                status.set("Ese producto ya estaba cargado.")
                return
            entry = build_entry(products, data, ml_id, aff, cat_var.get().strip() or None, source=link)
            products.append(entry)
            save_products(products)
        last_added["id"] = entry["id"]
        url_var.set("")
        aff_var.set("")
        cat_var.set("")
        refresh()
        if entry["image"]:
            status.set(f"Agregado en «{entry['category']}»: {entry['name']}{note}")
        else:
            status.set(f"Agregado «{entry['name']}» SIN imagen: sigo intentando en segundo plano "
                       f"(o usá «Buscar imágenes»).")
            auto_repair()
        if not store_state["opened"]:
            open_store()  # primera vez: abre la tienda con el producto; luego se actualiza sola

    def add(auto=False):
        link = url_var.get().strip()
        aff = aff_var.get().strip()
        if not re.match(r"https?://", link):
            messagebox.showwarning("Enlace inválido", "Pegá un enlace completo que empiece con https://")
            return
        if aff and not re.match(r"https?://", aff):
            messagebox.showwarning("Enlace de afiliado inválido", "El enlace de afiliado debe empezar con https://")
            return
        if not auto and not aff and not is_affiliate(link):
            if not messagebox.askyesno(
                    "Falta el enlace de afiliado",
                    "Cargaste solo el enlace normal del producto.\n\n"
                    "Si lo agregás así, la gente entra por ese enlace y NO cobrás comisión.\n\n"
                    "¿Agregarlo igual? (Después podés cambiarlo con «Editar»)"):
                return
        products = load_products()
        pre_id = find_ml_id(link)
        if any((pre_id and p.get("ml_id") == pre_id) or link in (p.get("link"), p.get("source"))
               or (aff and aff in (p.get("link"), p.get("source"))) for p in products):
            if auto:
                status.set("Ese producto ya estaba cargado.")
                url_var.set("")
                aff_var.set("")
            else:
                messagebox.showinfo("Ya existe", "Ese producto ya está cargado.")
            return
        set_busy(True)
        started = time.monotonic()
        total = TOTAL_BUDGET + IMAGE_BUDGET
        status.set("Leyendo la publicación...")

        def tick():
            if add_btn["state"] == "disabled":
                n = int(time.monotonic() - started)
                status.set(f"Leyendo la publicación... {n}s (máximo {total}s)")
                root.after(1000, tick)
        root.after(1000, tick)

        def work():
            try:
                box = {}
                th = threading.Thread(target=lambda: box.update(r=fetch_product(link)), daemon=True)
                th.start()
                th.join(total + 3)   # seguro: nunca esperar mas que esto
                data, ml_id = box.get("r", (None, pre_id))
                dup = bool(ml_id and any(p.get("ml_id") == ml_id for p in load_products()))
            except Exception:  # cualquier error: nunca dejar el boton bloqueado
                data, ml_id, dup = None, pre_id, False
            if dup:
                ui_q.put(lambda: (set_busy(False), status.set("Ese producto ya estaba cargado.")))
            else:
                ui_q.put(lambda: finish_add(link, data, ml_id, auto, aff))

        threading.Thread(target=work, daemon=True).start()

    def delete_selected():
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Eliminar", "Seleccioná uno o más productos de la lista.")
            return
        if not messagebox.askyesno("Eliminar", f"¿Eliminar {len(sel)} producto(s) de la tienda?"):
            return
        idx = {int(i) for i in sel}
        with DB_LOCK:
            products = [p for i, p in enumerate(load_products()) if i not in idx]
            save_products(products)
        refresh()

    def open_store():
        if not os.path.exists(os.path.join(BASE_DIR, "index.html")):
            messagebox.showerror("Error", "No encuentro index.html en:\n" + BASE_DIR)
            return
        port = start_server()
        if not port:
            messagebox.showerror("Error", "No pude iniciar el servidor local (puertos 8000-8020 ocupados).")
            return
        url = f"http://127.0.0.1:{port}/"
        if last_added["id"] is not None:
            url += f"?nuevo={last_added['id']}"  # el index resalta el producto recien agregado
        store_state["opened"] = True
        webbrowser.open(url)

    publish_state = {"running": False}

    def publicar():
        if publish_state["running"]:
            return
        if not os.path.exists(os.path.join(BASE_DIR, "index.html")):
            messagebox.showerror("Error", "No encuentro index.html en:\n" + BASE_DIR)
            return
        publish_state["running"] = True
        barra_ini()
        status.set("Publicando...")

        def work():
            modo = msg = err = None
            try:
                modo, msg = publish_site()
            except Exception as e:
                err = str(e)
                log(f"publicar fallo: {e}")

            barra_fin()

            def done():
                publish_state["running"] = False
                if err:
                    status.set("No se pudo publicar. Detalle en el cartel.")
                    messagebox.showerror("Publicar online", err)
                    return
                status.set(msg)
                if modo == "manual":
                    try:
                        os.startfile(SITE_DIR)
                    except AttributeError:
                        webbrowser.open("file://" + SITE_DIR)
                    webbrowser.open("https://app.netlify.com/drop")
                messagebox.showinfo("Publicar online", msg)
            ui_q.put(done)

        threading.Thread(target=work, daemon=True).start()

    def edit_selected():
        sel = tree.selection()
        if len(sel) != 1:
            messagebox.showinfo("Editar", "Seleccioná un solo producto de la lista.")
            return
        idx = int(sel[0])
        products = load_products()
        p = products[idx]
        win = tk.Toplevel(root)
        win.title(f"Editar producto {p.get('code', '')}".strip())
        win.configure(bg=BG)
        win.geometry("520x330")
        win.transient(root)
        vars_ = {}
        fields = [("Nombre", "name"), ("Precio (solo números)", "price"),
                  ("Imagen (enlace)", "image"), ("Enlace de afiliado", "link")]
        for r, (txt, key) in enumerate(fields):
            tk.Label(win, text=txt, bg=BG, fg=MUTED, font=("Segoe UI", 9)).grid(row=r * 2, column=0, sticky="w", padx=14, pady=(8, 0))
            v = tk.StringVar(value="" if p.get(key) is None else str(p.get(key)))
            vars_[key] = v
            tk.Entry(win, textvariable=v, bg=SURF, fg=TEXT, insertbackground=TEXT, relief="flat",
                     highlightthickness=1, highlightbackground=LINE).grid(row=r * 2 + 1, column=0, sticky="ew", padx=14, ipady=4)
        tk.Label(win, text="Categoría", bg=BG, fg=MUTED, font=("Segoe UI", 9)).grid(row=8, column=0, sticky="w", padx=14, pady=(8, 0))
        cv = tk.StringVar(value=p.get("category", ""))
        ttk.Combobox(win, textvariable=cv, values=all_categories(products)).grid(row=9, column=0, sticky="ew", padx=14)
        win.columnconfigure(0, weight=1)

        def save():
            pt = vars_["price"].get().strip()
            price = parse_price(pt)
            if pt and price is None:
                messagebox.showwarning("Precio", "El precio no es un número válido.", parent=win)
                return
            raw_img = vars_["image"].get().strip()
            new_img = clean_img_url(raw_img) or raw_img
            with DB_LOCK:
                fresh = load_products()
                if idx >= len(fresh):
                    win.destroy()
                    return
                q = fresh[idx]
                q["name"] = vars_["name"].get().strip() or q.get("name")
                registrar_precio(q, price)
                if new_img != (q.get("image") or ""):
                    q["image"] = new_img
                    q["images"] = [new_img] if new_img else []   # la imagen puesta a mano manda
                nuevo_link = vars_["link"].get().strip() or q.get("link")
                if nuevo_link != q.get("link"):
                    q["status"] = "disponible"   # enlace nuevo: vuelve a la tienda (verificalo para confirmar)
                    q["checked"] = None
                q["link"] = nuevo_link
                q["category"] = cv.get().strip() or q.get("category") or "Otros"
                save_products(fresh)
            refresh()
            win.destroy()

        button(win, "Guardar", save, MAGENTA).grid(row=10, column=0, pady=14)

    # Cola de más vendidos: abre cada producto en el navegador; cuando copiás su link de
    # afiliado se agrega al instante (con la foto/precio ya leídos) y abre el siguiente.
    COLA_PATH = os.path.join(BASE_DIR, "mas_vendidos.json")
    cola = {"activa": False, "items": [], "i": 0, "agregados": 0}

    def cola_pendientes():
        try:
            with open(COLA_PATH, encoding="utf-8") as f:
                items = json.load(f)
        except (OSError, ValueError):
            return []
        prods = load_products()
        ids = {p.get("ml_id") for p in prods if p.get("ml_id")}
        nombres = {_norm(p.get("name"))[:40] for p in prods}
        return [it for it in items if isinstance(it, dict) and it.get("url") and it.get("name")
                and it.get("ml_id") not in ids and _norm(it.get("name"))[:40] not in nombres]

    def cola_btn_txt():
        try:
            if cola["activa"]:
                cola_btn.config(text="⏹ Detener carga", bg="#8a1c3d")
            else:
                n = len(cola_pendientes())
                cola_btn.config(text=f"▶ Cargar más vendidos ({n})", bg="#7a2fd6")
        except NameError:
            pass

    def cola_abrir_actual():
        if cola["i"] >= len(cola["items"]):
            cola_parar(f"¡Listo! Cargaste {cola['agregados']} producto(s). Tocá «Publicar online».")
            return
        it = cola["items"][cola["i"]]
        barra(cola["i"], len(cola["items"]))
        status.set(f"[{cola['i'] + 1}/{len(cola['items'])}] {it['name'][:60]} — en Mercado Libre tocá "
                   "«Compartir» y copiá el link de afiliado (o «Saltear»).")
        webbrowser.open(it["url"])

    def cola_parar(msg=None):
        if cola["activa"]:
            cola["activa"] = False
            barra_fin()
        cola_skip_btn.pack_forget()
        cola_btn_txt()
        if msg:
            status.set(msg)

    def cola_toggle():
        if cola["activa"]:
            cola_parar(f"Carga detenida: {cola['agregados']} producto(s) agregados.")
            return
        items = cola_pendientes()
        if not items:
            messagebox.showinfo("Cargar más vendidos",
                                "No hay productos en la lista. Tocá primero «🔥 Más vendidos» para buscarlos.")
            return
        if not auto_var.get():
            auto_var.set(True)
        cola.update(activa=True, items=items, i=0, agregados=0)
        barra_ini()
        cola_btn_txt()
        cola_skip_btn.pack(side="left", padx=6, after=cola_btn)
        cola_abrir_actual()

    def cola_saltear():
        if cola["activa"]:
            cola["i"] += 1
            cola_abrir_actual()

    def cola_agregar(aff):
        """El link copiado es del producto que se abrió: se agrega sin volver a leer la página."""
        it = cola["items"][cola["i"]]
        data = {"name": it["name"], "price": it.get("price"), "currency": "ARS",
                "image": it.get("image") or "", "images": [it["image"]] if it.get("image") else [],
                "category": it.get("category")}
        with DB_LOCK:
            products = load_products()
            if not any(p.get("link") == aff for p in products):
                entry = build_entry(products, data, it.get("ml_id"), aff,
                                    normalize_category(it.get("category")), source=it["url"])
                entry["checked"] = time.strftime("%Y-%m-%d %H:%M")
                products.append(entry)
                save_products(products)
                cola["agregados"] += 1
                last_added["id"] = entry["id"]
        refresh()
        cola["i"] += 1
        root.after(700, cola_abrir_actual)

    clip = {"last": None}
    ML_RE = re.compile(r"https?://\S*(mercadolibre|mercadolivre|meli\.la|mercadopago)\S*", re.I)

    def watch_clipboard():
        try:
            txt = root.clipboard_get().strip()
        except tk.TclError:
            txt = ""
        if clip["last"] is None:
            clip["last"] = txt  # lo que ya estaba copiado al abrir no se carga
        elif txt != clip["last"]:
            clip["last"] = txt
            m = ML_RE.search(txt)
            if cola["activa"] and m and is_affiliate(m.group(0)):
                cola_agregar(m.group(0))
            elif auto_var.get() and m and add_btn["state"] == "normal":
                u = m.group(0)
                pendiente = url_var.get().strip()
                if is_affiliate(u):
                    if pendiente and not is_affiliate(pendiente):
                        aff_var.set(u)          # par completo: producto + afiliado
                    else:
                        url_var.set(u)          # solo afiliado: leo el producto a traves de el
                        aff_var.set("")
                    add(auto=True)
                else:
                    url_var.set(u)              # enlace normal: espero el de afiliado
                    aff_var.set("")
                    status.set("Enlace del producto guardado. Ahora copiá su ENLACE DE AFILIADO "
                               "(o pegalo abajo y tocá Agregar).")
        root.after(1000, watch_clipboard)

    def open_folder():
        try:
            os.startfile(BASE_DIR)
        except AttributeError:
            webbrowser.open("file://" + BASE_DIR)

    button(bottom, "Eliminar seleccionado", delete_selected, "#8a1c3d").pack(side="left")
    button(bottom, "Editar", edit_selected, "#2a3036").pack(side="left", padx=8)
    button(bottom, "Buscar imágenes", lambda: auto_repair(manual=True), "#2a3036").pack(side="left")
    cfg = load_config()
    auto_price_var = tk.BooleanVar(value=bool(cfg.get("auto_precios", False)))

    def on_auto_price_toggle():
        cfg["auto_precios"] = auto_price_var.get()
        save_config(cfg)

    update_price_btn = button(verify_row, "⚡ Actualizar Precios", lambda: toggle_actualizar_precios(True), "#0da9d9")
    update_price_btn.pack(side="left")
    tk.Checkbutton(verify_row, text="Auto al abrir", variable=auto_price_var,
                   command=on_auto_price_toggle, bg=BG, fg=TEXT, selectcolor=SURF,
                   activebackground=BG, activeforeground=TEXT, font=("Segoe UI", 9)
                   ).pack(side="left", padx=4)
    verify_btn = button(verify_row, "Verificar enlaces", lambda: verify_all(True), "#2a3036")
    verify_btn.pack(side="left", padx=6)
    purge_btn = button(verify_row, "Eliminar caídos", purge_dead, "#8a1c3d")
    purge_btn.pack(side="left")
    button(verify_row, "Diagnóstico", diagnose_selected, "#2a3036").pack(side="left", padx=6)

    def restaurar():
        sel = tree.selection()
        prods = load_products()
        ids = {prods[int(i)].get("id") for i in sel if int(i) < len(prods)} if sel else None
        alcance = f"los {len(sel)} producto(s) seleccionados" if sel else "TODOS los productos"
        if not messagebox.askyesno("Restaurar", f"Voy a:\n\n"
                                   f"• Marcar como DISPONIBLES {alcance} que estén en rojo/amarillo.\n"
                                   + ("" if sel else "• Volver a poner los que borró «Eliminar caídos» "
                                      "(eliminados_backup.json).\n")
                                   + "\n¿Continuar?"):
            return
        n_estado = reset_status(ids)
        n_borrados = 0 if sel else restore_backup()
        refresh()
        if n_estado or n_borrados:
            status.set(f"Restaurados: {n_estado} marcado(s) como disponible, {n_borrados} repuesto(s) del respaldo. "
                       "Tocá «Publicar online» para actualizar la tienda.")
        else:
            status.set("No había nada para restaurar.")
    button(verify_row, "Restaurar eliminados", restaurar, "#2a3036").pack(side="left")

    best_state = {"running": False}

    def mas_vendidos():
        """Busca los productos líderes de ML y abre un informe con los que todavía no tenés."""
        if best_state["running"]:
            return
        best_state["running"] = True
        barra_ini()
        status.set("Buscando los más vendidos de Mercado Libre (tarda unos minutos)...")

        def work():
            path, n, err = None, 0, None
            try:
                import buscar_mas_vendidos as bmv
                res = bmv.buscar(bmv.CATEGORIAS,
                                 progress=lambda m: ui_q.put(lambda m=m: status.set(m.strip())),
                                 paso=barra)
                path, n = bmv.informe(res)
            except Exception as e:
                err = str(e)
                log(f"mas_vendidos error: {e}")
            finally:
                best_state["running"] = False
                barra_fin()

            def done():
                if err:
                    status.set(f"No pude buscar los más vendidos: {err[:80]}")
                    return
                status.set(f"Encontré {n} producto(s) líderes que no tenés. Tocá «▶ Cargar más vendidos» para sumarlos rápido.")
                cola_btn_txt()
                webbrowser.open("file:///" + path.replace("\\", "/"))
            ui_q.put(done)

        threading.Thread(target=work, daemon=True).start()

    button(verify_row, "🔥 Más vendidos", mas_vendidos, "#df005b").pack(side="left", padx=6)
    cola_btn = button(verify_row, "▶ Cargar más vendidos", lambda: cola_toggle(), "#7a2fd6")
    cola_btn.pack(side="left")
    cola_skip_btn = button(verify_row, "Saltear ⏭", lambda: cola_saltear(), "#2a3036")
    cola_btn_txt()
    button(bottom, "Abrir tienda", open_store).pack(side="right")
    button(bottom, "Abrir carpeta", open_folder, "#2a3036").pack(side="right", padx=8)
    button(bottom, "Publicar online", publicar, "#1f8a4c").pack(side="right")
    if not os.path.exists(os.path.join(BASE_DIR, "index.html")):
        status.set("Ojo: no hay index.html en esta carpeta. Poné este programa junto a la tienda.")

    url_entry.bind("<Return>", lambda e: add())
    ensure_codes()   # productos de versiones anteriores: se les asigna código
    pump()
    watch_clipboard()
    url_entry.focus_set()
    refresh()
    if any(not p.get("image") for p in load_products()):
        auto_repair()   # productos viejos sin foto: se intenta completarlas solas
    root.after(4000, lambda: verify_all(manual=False, only_stale=True))   # revisión automática diaria
    if auto_price_var.get():
        root.after(6000, lambda: toggle_actualizar_precios(manual=False))
    root.mainloop()


if __name__ == "__main__":
    run_gui()

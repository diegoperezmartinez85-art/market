"""
Nexos Market - actualización automática en GitHub (corre sola todos los días).

1. Revisa cada producto en Mercado Libre: precio actual y si sigue disponible.
2. Marca las bajas de precio (para el cartel de descuento y la sección Ofertas).
3. Regenera las páginas de producto, el sitemap y productos.json.
4. Arma la página de ofertas y el kit diario para redes (ofertas/).

Seguridad:
- Nunca borra productos: los caídos quedan marcados "no disponible" (la tienda los muestra así).
- Si Mercado Libre bloquea la consulta (la mayoría sale "dudoso"), NO guarda nada:
  la tienda queda exactamente como estaba.
El workflow .github/workflows/actualizar.yml sube los cambios si los hay.
"""
import json
import os
import shutil
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.abspath(os.path.join(AQUI, "..", ".."))
sys.path.insert(0, AQUI)
os.environ.setdefault("TZ", "America/Argentina/Buenos_Aires")
try:
    time.tzset()
except AttributeError:
    pass

import gestor_nexos_v2 as g      # noqa: E402
import generar_paginas as gp     # noqa: E402
import generar_ofertas as go     # noqa: E402

TMP = os.environ.get("RUNNER_TEMP", "/tmp")
g.JSON_PATH = os.path.join(RAIZ, "productos.json")
g.LOG_PATH = os.path.join(TMP, "gestor_log.txt")
g.BACKUP_PATH = os.path.join(TMP, "eliminados_backup.json")
g.COUNTER_PATH = os.path.join(TMP, "contador.json")

MIN_OK = 0.5     # si menos de la mitad se pudo confirmar, se asume bloqueo y no se guarda nada


def resumen_md(lineas):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("\n".join(lineas) + "\n")


ALTAS = os.path.join(AQUI, "altas.json")


def _palabras(t):
    return {w for w in g._norm(t).replace("-", " ").split() if len(w) > 2}


def procesar_altas(lineas):
    """Agrega los productos de altas.json (link de afiliado + producto original). Nunca borra nada."""
    try:
        cola = json.load(open(ALTAS, encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not cola:
        return
    products = g.load_products()
    ya = {p.get("link") for p in products}
    pendientes, agregados = [], 0
    lineas.append("## Altas de productos")
    for it in cola:
        if it["link"] in ya:
            lineas.append(f"- {it['n']}. ya estaba: {it['esperado']}")
            continue
        data, ml_id = g.fetch_product(it["link"])          # lo que realmente abre el link de afiliado
        data_src, id_src = g.fetch_product(it["source"])
        if not data and not data_src:
            pendientes.append(it)
            lineas.append(f"- {it['n']}. no se pudo leer (se reintenta mañana): {it['esperado']}")
            continue
        base = data if (data and data.get("image") and data.get("price")) else (data_src or data)
        aviso = ""
        if data and data_src:
            comun = _palabras(data["name"]) & _palabras(data_src["name"])
            if len(comun) < 2:
                aviso = f" ⚠ el link abre «{data['name']}», no «{data_src['name']}»"
                base = data
        q = g.build_entry(products, base, ml_id or id_src, it["link"],
                          category_override=it.get("category") if not aviso else None, source=it["source"])
        products.append(q)
        agregados += 1
        lineas.append(f"- {it['n']}. {q['code']} {q['name']} · {q.get('price')}{aviso}")
    g.save_products(products)
    with open(ALTAS, "w", encoding="utf-8") as f:
        json.dump(pendientes, f, ensure_ascii=False, indent=1)
    lineas.append(f"- Agregados: {agregados} · pendientes: {len(pendientes)}")


def main():
    altas = []
    try:
        procesar_altas(altas)
    except Exception as e:
        altas.append(f"- Altas: error ({e})")
    print("\n".join(altas), flush=True)
    respaldo = os.path.join(TMP, "productos_antes.json")
    shutil.copyfile(g.JSON_PATH, respaldo)
    total = len(g.load_products())
    print(f"Revisando {total} productos...", flush=True)

    def prog(n, t, p):
        if n % 10 == 0 or n == t:
            print(f"  {n}/{t}", flush=True)

    res = g.verify_links(progress=prog)
    ok = res["disponible"] + res["no_disponible"]
    lineas = altas + [
        "## Actualización de precios",
        f"- Revisados: {total}",
        f"- Disponibles: {res['disponible']}",
        f"- No disponibles: {res['no_disponible']}",
        f"- Sin confirmar (dudosos): {res['dudoso']}",
        f"- Precios que cambiaron: {len(res['precios'])}",
    ]
    for code, antes, ahora in res["precios"][:40]:
        lineas.append(f"  - {code}: {antes} -> {ahora}")

    if total and ok < total * MIN_OK:
        shutil.copyfile(respaldo, g.JSON_PATH)
        lineas.append("")
        lineas.append(f"**Mercado Libre no respondió bien ({ok}/{total} confirmados). "
                      "No se guardó ningún cambio: la tienda queda como estaba.**")
        print("\n".join(lineas))
        resumen_md(lineas)
        sys.exit(2)

    n = gp.generar(RAIZ, g.load_products())
    lineas.append(f"- Páginas regeneradas: {n}")
    try:
        r = go.generar(RAIZ, g.load_products())
        lineas.append(f"- Ofertas: {r['ofertas']} en la página · kit del día: {r['kit']} (fotos {r['fotos_ok']})")
    except Exception as e:      # el kit nunca frena la actualización de precios
        lineas.append(f"- Kit de ofertas: error ({e})")
    print("\n".join(lineas))
    resumen_md(lineas)


if __name__ == "__main__":
    main()

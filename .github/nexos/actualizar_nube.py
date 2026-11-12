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


def main():
    respaldo = os.path.join(TMP, "productos_antes.json")
    shutil.copyfile(g.JSON_PATH, respaldo)
    total = len(g.load_products())
    print(f"Revisando {total} productos...", flush=True)

    def prog(n, t, p):
        if n % 10 == 0 or n == t:
            print(f"  {n}/{t}", flush=True)

    res = g.verify_links(progress=prog)
    ok = res["disponible"] + res["no_disponible"]
    lineas = [
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

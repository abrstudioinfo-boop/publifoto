"""Prepara las plantillas de CARTAS desde los TIFF con capas de cada equipo (2026).

Cada TIFF trae, de abajo arriba:
  - la carta entera por detrás (con el logo y el nombre del equipo ya puestos);
  - «Place Your Image Here»: un jugador de ejemplo con la máscara de dónde se ve;
  - encima, la capa que corta al jugador en la línea dorada y la de los textos.

El jugador va entre la carta de detrás y las capas de encima, con la sombra de
Photoshop del jugador de ejemplo (medida en la plantilla: ver medir_sombra). No se cambia
ni el logo ni el nombre: cada equipo tiene su plantilla.

Se guarda: fondo.png (la carta de detrás), encima.png (las capas de encima, RGBA) y
mascara.png (dónde se ve el jugador).

Uso:
  python -m publifoto.herramientas.preparar_carta_capas CARPETA_CON_LOS_TIF [CARPETA_PLANTILLA]
"""
import itertools
import json
import os
import sys

import cv2
import numpy as np
from PIL import Image

from .tiff_capas import leer_capas

Image.MAX_IMAGE_PIXELS = None
HUECO = "place your image"

# la sombra del jugador en las plantillas de 2026 (medida en la de Tortosa): la silueta
# crecida «crece» px, difuminada (sigma «difumina» px), bajada «dy» px y con esta fuerza
SOMBRA = {"crece": 16, "difumina": 36, "dx": -4, "dy": 84, "fuerza": 0.40}

# equipos: archivo (sin PLANTILLA2026.tif) -> (clave, nombre del color, nombre del club, palabras)
# la clave None es la plantilla principal (la de Amposta)
EQUIPOS = {
    "BONAAMPOSTA": (None, "Amposta", "C.F. AMPOSTA", ["amposta"]),
    "ATMELLA": ("ametlla", "L'Ametlla de Mar", "SECER L'ATMELLA DE MAR", ["ametlla", "atmella"]),
    "BATEA": ("batea", "Batea", "C.F. BATEA", ["batea"]),
    "CATALONIA": ("catalonia", "Catalonia", "JESÚS CATALONIA", ["catalonia"]),
    "JESUSYMARIA": ("jesusimaria", "Jesús i Maria", "U.D. JESÚS I MARIA", ["jesus"]),
    "LACAVA": ("lacava", "La Cava", "ESCOLA DE FUTBOL LA CAVA", ["cava"]),
    "TORTOSA": ("tortosa", "Tortosa", "C.F. TORTOSA EBRE", ["tortosa"]),
}


def _lienzo(c, W, H):
    out = np.zeros((H, W, 4), np.float32)
    x0, y0, x1, y1 = c["caja"]
    xa, ya, xb, yb = max(0, x0), max(0, y0), min(W, x1), min(H, y1)
    if xb > xa and yb > ya:
        out[ya:yb, xa:xb] = np.asarray(c["imagen"], np.float32)[ya - y0:yb - y0, xa - x0:xb - x0]
    return out


def leer(ruta):
    """Devuelve dict con detras (HxWx3), encima (HxWx4, sin premultiplicar), mascara
    (HxW uint8), el jugador de ejemplo (HxWx4), la imagen final y avisos."""
    (W, H), modo, capas = leer_capas(ruta)
    if modo not in ("RGB", "CMYK"):
        raise ValueError(f"La carta está en {modo}: tiene que estar en RGB o CMYK.")
    huecos = [k for k, c in enumerate(capas) if HUECO in c["nombre"].lower()]
    if not huecos:
        raise ValueError("No tiene la capa «Place Your Image Here» (el jugador de ejemplo).")
    i = huecos[0]
    avisos = []
    if i == 0:
        raise ValueError("Falta la carta por detrás del jugador (alguna capa debajo de «Place Your Image Here»).")
    # detrás: las capas visibles de debajo del jugador
    detras = np.full((H, W, 3), 255, np.float32)
    for c in capas[:i]:
        if not c["visible"]:
            continue
        l = _lienzo(c, W, H)
        a = l[:, :, 3:4] / 255 * c["opacidad"] / 255
        detras = l[:, :, :3] * a + detras * (1 - a)
    # encima: todas las capas de encima, también las ocultas (la que corta al jugador
    # puede venir oculta en el archivo)
    pm = np.zeros((H, W, 3), np.float32)          # color premultiplicado
    al = np.zeros((H, W, 1), np.float32)
    for c in capas[i + 1:]:
        if not c["visible"]:
            avisos.append(f"la capa «{c['nombre']}» estaba oculta y se usa igual")
        l = _lienzo(c, W, H)
        a = l[:, :, 3:4] / 255 * c["opacidad"] / 255
        pm = l[:, :, :3] * a + pm * (1 - a)
        al = a + al * (1 - a)
    if not capas[i + 1:]:
        avisos.append("no hay ninguna capa encima del jugador: no se corta")
    color = np.where(al > 0, pm / np.maximum(al, 1e-6), 0)
    encima = np.dstack([color, al[:, :, 0] * 255])
    hu = capas[i]
    m = hu.get("mascara")
    if m:
        ml, mt, mr, mb = m["caja"]
        mascara = np.full((H, W), m["defecto"], np.uint8)
        xa, ya, xb, yb = max(0, ml), max(0, mt), min(W, mr), min(H, mb)
        mascara[ya:yb, xa:xb] = np.asarray(m["imagen"])[ya - mt:yb - mt, xa - ml:xb - ml]
    else:
        mascara = np.full((H, W), 255, np.uint8)
        avisos.append("«Place Your Image Here» no tiene máscara: el jugador se ve en toda la carta")
    final = np.asarray(Image.open(ruta).convert("RGB"), np.float32)
    return dict(W=W, H=H, detras=detras, encima=encima, mascara=mascara, ejemplo=_lienzo(hu, W, H),
                final=final, avisos=avisos)


def _sombra(alfa, s, corte=None):
    """Factor (HxW, 1 = sin sombra) con que la sombra oscurece lo de detrás."""
    sil = alfa
    if s["crece"]:
        r = int(round(s["crece"]))
        sil = cv2.dilate(sil, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
    sil = np.roll(sil, (int(s.get("dy", 0)), int(s.get("dx", 0))), (0, 1))
    return 1 - s["fuerza"] * cv2.GaussianBlur(sil, (0, 0), s["difumina"])


def componer_ejemplo(d, s):
    """La carta con el jugador de ejemplo, como la compone el programa (para comprobar)."""
    a = d["ejemplo"][:, :, 3] / 255 * d["mascara"] / 255
    carta = d["detras"] * _sombra(a, s)[..., None]
    carta = d["ejemplo"][:, :, :3] * a[..., None] + carta * (1 - a[..., None])
    ea = d["encima"][:, :, 3:4] / 255
    return d["encima"][:, :, :3] * ea + carta * (1 - ea)


def medir_sombra(d, k=2):
    """Ajusta la sombra (crece, difumina, dx, dy, fuerza) a la del jugador de ejemplo."""
    W, H = d["W"], d["H"]
    a = d["ejemplo"][:, :, 3] / 255 * d["mascara"] / 255
    ea = d["encima"][:, :, 3] / 255
    zona = (a < 0.01) & (ea < 0.01) & (d["detras"].sum(2) > 60)
    D = np.where(zona, 1 - d["final"].sum(2) / np.maximum(d["detras"].sum(2), 1), 0)
    pq = (W // k, H // k)
    a4 = cv2.resize(a, pq, interpolation=cv2.INTER_AREA)
    D4 = cv2.resize(D.astype(np.float32), pq, interpolation=cv2.INTER_AREA)
    z4 = cv2.resize(zona.astype(np.float32), pq, interpolation=cv2.INTER_AREA) > 0.99
    mejor = None
    for crece, dif, dx, dy in itertools.product(range(0, 33, 4), range(20, 53, 4), (-8, -4, 0, 4, 8),
                                                range(0, 121, 8)):
        s = a4
        if crece:
            r = max(1, round(crece / k))
            s = cv2.dilate(s, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
        s = cv2.GaussianBlur(np.roll(s, (round(dy / k), round(dx / k)), (0, 1)), (0, 0), dif / k)
        x, y = s[z4], D4[z4]
        fu = float((x * y).sum() / max((x * x).sum(), 1e-9))
        e = float(((y - fu * x) ** 2).mean())
        if mejor is None or e < mejor[0]:
            mejor = (e, dict(crece=crece, difumina=dif, dx=dx, dy=dy, fuerza=round(fu, 3)))
    return mejor[1]


def error(d, s):
    """Diferencia (máxima y p99, de 0 a 255) entre la plantilla y lo que hace el programa."""
    dif = np.abs(componer_ejemplo(d, s) - d["final"]).max(2)
    return float(dif.max()), float(np.percentile(dif, 99.9))


def guardar(d, carpeta, mascara=True):
    os.makedirs(carpeta, exist_ok=True)
    Image.fromarray(np.clip(d["detras"] + .5, 0, 255).astype(np.uint8)).save(os.path.join(carpeta, "fondo.png"))
    Image.fromarray(np.clip(d["encima"] + .5, 0, 255).astype(np.uint8), "RGBA").save(
        os.path.join(carpeta, "encima.png"))
    if mascara:
        Image.fromarray(d["mascara"]).save(os.path.join(carpeta, "mascara.png"))


def plantilla_base(W, H, nombre_club, buscar, sombra=SOMBRA, anterior=None, nombre_color="Amposta"):
    """El plantilla.json de las cartas (formato «capas»). anterior: el de antes, del que se
    guardan el encuadre y la colocación del jugador (las medidas que ya se usaban)."""
    from .preparar_carta import _colocacion
    a = anterior or {}
    return {
        "id": "cartas", "nombre": "CARTAS", "tipo": "carta", "color": "CMYK", "lienzo": [W, H], "ppp": 300,
        "formato": "capas",
        "fondo": "fondo.png", "mascara": "mascara.png", "encima": "encima.png", "sombra": dict(sombra),
        "nombre_color": nombre_color,
        "club": {"texto": nombre_club},
        "buscar": list(buscar),
        "variantes": {},
        "huecos": [{"rect": [0, 0, W, H]}], "jugadores_por_hoja": 1,
        "encuadre": a.get("encuadre", {"margen": 0.1475, "alto_rel": 5.69, "centro": 0.0, "referencia": "mixto"}),
        "impresion": ["tif"], "editable": "psd", "archivo": "CARTA {FOTO}",
        "un_archivo": "CARTAS {EQUIPO}", "pdf_copias": {"jugador": 1},
        "excluir": ["entrenador", "equipo"], "necesita_recorte": True,
        "colocacion": a.get("colocacion") if list(a.get("lienzo", [])) == [W, H] and a.get("colocacion")
        else _colocacion(W, H),
    }


def main(ruta_tif, carpeta=None, nombre_club=None, buscar=None, medir=False):
    """Una sola carta (la que se actualiza desde el programa). Devuelve la carpeta."""
    from .. import productos
    carpeta = carpeta or os.path.join(productos.PLANTILLAS, "cartas")
    d = leer(ruta_tif)
    s = medir_sombra(d) if medir else SOMBRA
    print("sombra:", s, "error (máx, p99.9):", error(d, s))
    for a in d["avisos"]:
        print("aviso:", a)
    guardar(d, carpeta)
    clave = os.path.basename(ruta_tif).upper().replace("PLANTILLA2026", "").rsplit(".", 1)[0]
    eq = EQUIPOS.get(clave)
    p = plantilla_base(d["W"], d["H"], nombre_club or (eq[2] if eq else ""), buscar or (eq[3] if eq else []), s,
                       nombre_color=eq[1] if eq else "Plantilla")
    with open(os.path.join(carpeta, "plantilla.json"), "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    return carpeta


def todas(carpeta_tif, carpeta=None, anterior=None):
    """Las 7 plantillas de los equipos: la de Amposta y las otras como variantes."""
    from .. import productos
    carpeta = carpeta or os.path.join(productos.PLANTILLAS, "cartas")
    p = None
    for archivo, (clave, nombre, club, buscar) in sorted(EQUIPOS.items(), key=lambda kv: kv[1][0] is not None):
        ruta = os.path.join(carpeta_tif, archivo + "PLANTILLA2026.tif")
        d = leer(ruta)
        print(archivo, "error (máx, p99.9):", [round(x, 1) for x in error(d, SOMBRA)], *d["avisos"])
        if clave is None:
            guardar(d, carpeta)
            p = plantilla_base(d["W"], d["H"], club, buscar, SOMBRA, anterior)
            mascara0 = d["mascara"]
        else:
            if list(p["lienzo"]) != [d["W"], d["H"]] or not np.array_equal(d["mascara"], mascara0):
                raise ValueError(f"{archivo}: otra medida u otro hueco que la de Amposta")
            guardar(d, os.path.join(carpeta, "variantes", clave), mascara=False)
            p["variantes"][clave] = {"nombre": nombre, "carpeta": f"variantes/{clave}", "buscar": buscar,
                                     "club": {"texto": club}}
        del d
    with open(os.path.join(carpeta, "plantilla.json"), "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    return carpeta


if __name__ == "__main__":
    todas(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

"""CARTAS: el jugador recortado se coloca en la carta.

El recorte y la colocación son los de la sesión CARTAS (carta_auto.py): el programa
recorta solo desde la foto arreglada, o usa el PNG del cliente si sube RECORTADAS. Ver
herramientas/preparar_carta.py para cómo se prepara la plantilla.

Plantillas de carta: la plantilla trae la carta de un equipo (Amposta) y, en «variantes»,
las de los otros equipos. Desde 2026 (formato «capas», ver herramientas/preparar_carta_capas.py)
cada plantilla ya lleva el escudo y el nombre de su equipo y no se cambian: el jugador va
entre la carta de detrás y las capas de encima (la que lo corta en la línea dorada y los
textos), con su sombra.
"""
import os
import threading
import unicodedata

import cv2
import numpy as np
from PIL import Image

from . import color, productos
from .herramientas.preparar_carta import aplicar_lut
from .herramientas.preparar_carta_capas import _sombra

_cache = {}
_cache_club = {}
_girados = {}
_cerrojo = threading.Lock()      # MediaPipe no se puede usar desde dos hilos a la vez
COLOR_PLANTILLA = "Amposta"   # el color con el que viene la plantilla (sin variante)


# --- colores de carta ----------------------------------------------------------

def _simple(texto):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in t if ch.isalnum())


def colores(p):
    """[(clave, nombre)] de los colores de carta: None es el de la plantilla."""
    vs = sorted(p.get("variantes", {}).items(), key=lambda kv: _simple(kv[1]["nombre"]))
    return [(None, p.get("nombre_color", COLOR_PLANTILLA))] + [(k, v["nombre"]) for k, v in vs]


# escudos de otros deportes del mismo pueblo (AMPOSTA BASQUET no es el C.F. Amposta)
_OTRO_DEPORTE = ("basquet", "basket", "handbol", "handball", "hoquei", "hockey", "volei", "voley", "rugbi",
                 "rugby", "patinatge", "natacio", "atletisme", "tennis")


def _de_futbol(n):
    return not any(d in n for d in _OTRO_DEPORTE)


def color_para(p, nombre_escudo):
    """El color de carta que va con el escudo elegido (por su nombre), o None (el de la
    plantilla) si ninguno lo nombra."""
    n = _simple(nombre_escudo)
    if not n or not _de_futbol(n):
        return None
    for clave, v in p.get("variantes", {}).items():
        if any(_simple(b) in n for b in v.get("buscar", [])):
            return clave
    return None


def es_club_de_plantilla(p, nombre_escudo):
    """¿El escudo elegido es el del club de la plantilla (el de Amposta)?"""
    n = _simple(nombre_escudo)
    return bool(n) and _de_futbol(n) and any(_simple(b) in n for b in p.get("buscar", []))


def es_del_equipo(p, nombre_escudo, clave):
    """¿El escudo es del equipo de la plantilla 'clave' (None: la de Amposta)?"""
    if clave:
        return color_para(p, nombre_escudo) == clave
    return es_club_de_plantilla(p, nombre_escudo)


def con_plantilla(p, nombre_escudo):
    """¿El escudo es de un equipo que tiene plantilla de carta propia?"""
    return color_para(p, nombre_escudo) is not None or es_club_de_plantilla(p, nombre_escudo)


def _variante(p, clave):
    """(carpeta, datos del club) del color de carta 'clave'."""
    v = p.get("variantes", {}).get(clave) if clave else None
    if v is None:
        return p["_carpeta"], p.get("club", {})
    return v.get("_ruta") or os.path.join(p["_carpeta"], *v["carpeta"].split("/")), v.get("club", {})


def nombre_club(p, clave=None):
    """El nombre del club que lleva el color de carta 'clave' si no se escribe otro."""
    return _variante(p, clave)[1].get("texto", "")


def _plantilla_px(p, clave=None):
    # por carpeta y fecha: al actualizar la plantilla se vuelve a leer
    c, _ = _variante(p, clave)
    base = p["_carpeta"]
    id_ = (c, os.path.getmtime(os.path.join(c, p["fondo"])))
    if id_ not in _cache:
        if len(_cache) > 1:               # el de la plantilla y el del club elegido, como mucho
            _cache.clear()
        _cache[id_] = dict(
            fondo=np.asarray(Image.open(os.path.join(c, p["fondo"])).convert("RGB"), np.float32),
            mascara=np.asarray(Image.open(os.path.join(base, p["mascara"])), np.float32) / 255,
            encima=np.asarray(Image.open(os.path.join(c, p["encima"])), np.float32),
            lut=np.load(os.path.join(c, p["lut"])) if p.get("lut") else None,
            sombra=p["sombra"] if isinstance(p.get("sombra"), dict) else None,
        )
    return _cache[id_]


SRA3_MM = (320, 450)


def hoja_mm(p):
    """La página del PDF de las cartas: SRA3 justo (320 x 450 mm) si la carta cabe, aunque
    en píxeles dé unas centésimas más (3780 px a 300 ppp son 320,04 mm); si no cabe, la
    medida de la carta."""
    if p.get("hoja_mm"):
        return list(p["hoja_mm"])
    ppp = p.get("ppp", 300)
    if all(v <= round(mm / 25.4 * ppp) for v, mm in zip(p["lienzo"], SRA3_MM)):
        return list(SRA3_MM)
    return [v / ppp * 25.4 for v in p["lienzo"]]


def fondo_club(p, clave=None, marca=None):
    """La carta sin jugador de la plantilla 'clave' (None: la de Amposta). Devuelve (carta
    HxWx3 float, capas para el PSD). El escudo y el nombre son los de la plantilla de cada
    equipo: no se cambian ('marca' no se usa en las cartas)."""
    t = _plantilla_px(p, clave)
    fondo = Image.fromarray(np.clip(t["fondo"] + .5, 0, 255).astype(np.uint8))
    if p.get("formato") != "capas":
        return t["fondo"], [("Fondo", fondo, None, 0, 0)]
    # formato «capas»: la carta de detrás con las capas de encima (corte y textos)
    c, _ = _variante(p, clave)
    id_ = (c, os.path.getmtime(os.path.join(c, p["fondo"])), os.path.getmtime(os.path.join(c, p["encima"])))
    if id_ not in _cache_club:
        e = t["encima"]
        ea = e[:, :, 3:4] / 255
        if len(_cache_club) > 1:
            _cache_club.clear()
        _cache_club[id_] = (e[:, :, :3] * ea + t["fondo"] * (1 - ea), [("Fondo", fondo, None, 0, 0)])
    return _cache_club[id_]


def _componer_capas(p, clave, t, jugador, k, alfa):
    """Formato «capas»: la carta de detrás, la sombra y el jugador (solo donde deja ver la
    máscara) y encima las capas que lo cortan y los textos, como en Photoshop."""
    W, H = p["lienzo"]
    completa, capas = fondo_club(p, clave)
    capas = list(capas)
    carta = completa.copy()
    ys, xs = np.nonzero(alfa > 0.002)
    if len(ys):
        s = t["sombra"]
        m = int(s["crece"] + 3 * s["difumina"] + abs(s.get("dy", 0)) + abs(s.get("dx", 0))) if s else 4
        y0, y1 = max(0, ys.min() - m), min(H, ys.max() + 1 + m)
        x0, x1 = max(0, xs.min() - m), min(W, xs.max() + 1 + m)
        sl = (slice(y0, y1), slice(x0, x1))
        a = alfa[sl]
        jug = k[sl][:, :, :3] if t["lut"] is None else aplicar_lut(k[sl][:, :, :3], t["lut"])
        z = t["fondo"][sl]
        if s:
            f = _sombra(a, s)
            z = z * f[..., None]
            # negro con esta opacidad = oscurecer lo de detrás como la sombra de Photoshop
            capas.append(("Sombra", Image.fromarray(np.dstack([np.zeros(a.shape + (3,), np.uint8),
                                                               np.clip((1 - f) * 255 + .5, 0, 255).astype(np.uint8)]),
                                                    "RGBA"), None, int(x0), int(y0)))
        z = jug * a[..., None] + z * (1 - a[..., None])
        e = t["encima"][sl]
        ea = e[:, :, 3:4] / 255
        carta[sl] = e[:, :, :3] * ea + z * (1 - ea)
        capas.append((jugador.nombre, Image.fromarray(np.clip(np.dstack([jug, a * 255]) + .5, 0, 255).astype(np.uint8),
                                                      "RGBA"), None, int(x0), int(y0)))
    capas.append(("Corte y textos", Image.fromarray(np.clip(t["encima"] + .5, 0, 255).astype(np.uint8), "RGBA"),
                  None, 0, 0))
    return Image.fromarray(np.clip(carta + .5, 0, 255).astype(np.uint8)), capas


def componer(p, jugador, ajuste=None, clave=None, marca=None):
    """Devuelve (carta RGB, capas para el PSD). clave: el color de carta (None, el de la
    plantilla); marca: {escudo, club} del club."""
    t = _plantilla_px(p, clave)
    fondo, capas = fondo_club(p, clave, marca)
    capas = list(capas)
    W, H = p["lienzo"]
    from . import carta_auto, retoque
    png, med = jugador.carta
    rec = retoque.de_jugador(jugador, Image.open(png).convert("RGBA"))
    col = p.get("colocacion", carta_auto.COLOCACION)
    # el giro de la revisión rápida (endereza al jugador en todos los productos): se gira el
    # recorte y se vuelve a medir dónde va, como cualquier otro jugador
    giro = productos.giro_total(jugador, p)
    if giro:
        from .analisis import girar
        rec = girar(rec, giro)
        clave_giro = (png, os.path.getmtime(png), giro)
        with _cerrojo:
            if clave_giro not in _girados:
                _girados[clave_giro] = carta_auto.medir_colocacion(rec, col)
        med = _girados[clave_giro]
    kid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    kid.paste(carta_auto.colocar(rec, med, col, ajuste), tuple(col["caja"][:2]))
    k = np.asarray(kid, np.float32)
    alfa = k[:, :, 3] / 255 * t["mascara"]
    if p.get("formato") == "capas":
        return _componer_capas(p, clave, t, jugador, k, alfa)
    zona = alfa > 0.002
    ys, xs = np.nonzero(zona)
    carta = fondo.copy()
    if len(ys):
        sombra = t["sombra"]
        m = int(sombra["crece"] + 3 * sombra["difumina"]) if sombra else 4
        # zona que se rehace: el jugador y su sombra alrededor (la de Photoshop)
        y0, y1 = max(0, ys.min() - m), min(H, ys.max() + 1 + m)
        x0, x1 = max(0, xs.min() - m), min(W, xs.max() + 1 + m)
        sl = (slice(y0, y1), slice(x0, x1))
        jug = k[sl][:, :, :3] if t["lut"] is None else aplicar_lut(k[sl][:, :, :3], t["lut"])
        a = alfa[sl][..., None]
        # detrás del jugador, la carta entera (adornos, textos y escudo van debajo de él:
        # el jugador no lo tapa nada salvo la línea dorada que lo corta)
        bajo = fondo[sl]
        e = t["encima"][sl]
        ea = e[:, :, 3:4] / 255
        # la línea dorada y lo que hay por debajo de ella sí van encima del jugador
        linea = max(0, p.get("linea", col["corte"] - 3) - y0)
        ea = ea.copy()
        ea[:linea] = 0
        oscuro = None
        if sombra is not None:
            r = int(sombra["crece"])
            # el jugador sale de detrás de la línea dorada: para la sombra se le alarga hacia
            # abajo (como si siguiera) y así llega entera hasta la línea, que la corta
            silueta = alfa[sl].copy()
            c = col["corte"] - y0
            if 0 < c <= silueta.shape[0]:
                fila = silueta[max(0, c - 3):c].max(0)
                silueta = np.vstack([silueta[:c], np.repeat(fila[None], m, 0)])
            crecido = cv2.dilate(silueta, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)))
            f = 1 - sombra["fuerza"] * cv2.GaussianBlur(crecido, (0, 0), sombra["difumina"])[:alfa[sl].shape[0]]
            # el jugador sigue por debajo de la línea dorada: ahí no cae sombra
            f[max(0, col["corte"] - y0):] = 1
            bajo = bajo * f[..., None]
            oscuro = (1 - f) * t["mascara"][sl]       # para la capa «Sombra» del PSD
        comp = jug * a + bajo * (1 - a)
        comp = e[:, :, :3] * ea + comp * (1 - ea)
        # solo dentro del hueco de la foto; fuera, la carta tal cual
        mk = t["mascara"][sl][..., None]
        carta[sl] = comp * mk + carta[sl] * (1 - mk)
        if oscuro is not None and oscuro.max() > 0:
            # negro con esta opacidad = oscurecer el fondo como la sombra de Photoshop
            capas.append(("Sombra", Image.fromarray(np.dstack([np.zeros(oscuro.shape + (3,), np.uint8),
                                                               np.clip(oscuro * 255 + .5, 0, 255).astype(np.uint8)]),
                                                    "RGBA"), None, int(x0), int(y0)))
        jug_rgba = np.dstack([jug, alfa[sl] * 255]).astype(np.uint8)
        capas.append((jugador.nombre, Image.fromarray(np.clip(jug_rgba, 0, 255), "RGBA"), None, int(x0), int(y0)))
        enc = np.dstack([e[:, :, :3], ea[:, :, 0] * 255]).astype(np.uint8)
        if enc[:, :, 3].any():
            capas.append(("Línea dorada", Image.fromarray(enc, "RGBA"), None, int(x0), int(y0)))
    return Image.fromarray(np.clip(carta + .5, 0, 255).astype(np.uint8)), capas


def generar(p, jugadores, equipo, ajustes, imp, edi, progreso=print, hilos=None, clave=None, marca=None):
    if clave is not None and clave not in p.get("variantes", {}):
        progreso(f"  CARTAS: el color «{clave}» ya no está en la plantilla, se usa el de la plantilla")
        clave = None
    fondo_club(p, clave, marca)          # una vez, antes de repartir a los jugadores en hilos
    # para imprimir, como el calendario de pared: un TIFF por capas con todas y un PDF con una
    # carta en cada página SRA3 (320 x 450 mm justos). En el TIFF, con las plantillas por capas,
    # se pueden editar los jugadores: abajo la carta de detrás, una capa por jugador (con su
    # sombra) y arriba el corte y los textos; se ve el último jugador y los demás tienen el ojo
    # apagado. Con las plantillas antiguas, una capa por carta entera.
    tif = hojas = None
    editable = p.get("formato") == "capas"
    if p.get("un_archivo"):
        nombre_todos = productos.nombre_archivo(dict(p, archivo=p["un_archivo"]), equipo)
        tif = productos.TIFFPorCapas(tuple(p["lienzo"]), "CMYK")
        hojas = productos.PDFCopias(os.path.join(imp, nombre_todos), hoja_mm(p), p.get("ppp", 300),
                                    p.get("pdf_copias") or {"jugador": 1})
        if editable:
            tif.añadir(*fondo_club(p, clave)[1][0])

    def una(j):
        if not getattr(j, "carta", None):
            progreso(f"  CARTAS: no se ha podido recortar a {j.nombre}, se salta")
            return [], None, None
        progreso(f"  CARTAS: {j.nombre}")
        return _una(p, j, equipo, ajustes, imp, edi, clave, marca, suelta=tif is None)
    hechas = hilos.map(una, jugadores) if hilos else map(una, jugadores)
    salidas, ultima, de_jugadores = [], None, []
    for j, (hechos, carta_cmyk, capa) in zip(jugadores, hechas):     # en el orden de los jugadores
        salidas += hechos
        if tif is not None and carta_cmyk is not None:
            if editable:
                if capa is not None:
                    for i in de_jugadores:
                        tif.ver(i, False)             # se ve solo el último
                    tif.añadir(j.nombre, *capa)
                    de_jugadores.append(len(tif.capas) - 1)
            else:
                tif.añadir(j.nombre, carta_cmyk, None, 0, 0)
            hojas.añadir(carta_cmyk, j.tipo)
            ultima = carta_cmyk
    if tif is not None and ultima is not None:
        if editable:
            t = _plantilla_px(p, clave)
            tif.añadir("Corte y textos", Image.fromarray(np.clip(t["encima"] + .5, 0, 255).astype(np.uint8),
                                                         "RGBA"), None, 0, 0)
        salidas.append(tif.guardar(os.path.join(imp, nombre_todos), ultima))
        salidas.append(hojas.cerrar())
    return salidas


def _jugador_con_sombra(capas):
    """Las capas de un jugador (su sombra debajo y él encima) en una sola, para que en el
    TIFF con todos se mueva con su sombra. Devuelve (RGBA, None, x, y)."""
    capas = [c for c in capas if c[1] is not None]
    if not capas:
        return None
    x0 = min(c[3] for c in capas)
    y0 = min(c[4] for c in capas)
    x1 = max(c[3] + c[1].width for c in capas)
    y1 = max(c[4] + c[1].height for c in capas)
    rgb = np.zeros((y1 - y0, x1 - x0, 3), np.float32)
    a = np.zeros((y1 - y0, x1 - x0), np.float32)
    for _, im, _, x, y in capas:                      # de abajo arriba
        c = np.asarray(im.convert("RGBA"), np.float32)
        sl = (slice(y - y0, y - y0 + im.height), slice(x - x0, x - x0 + im.width))
        ca = c[:, :, 3] / 255
        ab = a[sl]
        na = ca + ab * (1 - ca)
        mezcla = c[:, :, :3] * ca[..., None] + rgb[sl] * (ab * (1 - ca))[..., None]
        rgb[sl] = mezcla / np.maximum(na, 1e-6)[..., None]
        a[sl] = na
    im = Image.fromarray(np.clip(np.dstack([rgb, a * 255]) + .5, 0, 255).astype(np.uint8), "RGBA")
    return im, None, int(x0), int(y0)


def _una(p, j, equipo, ajustes, imp, edi, clave=None, marca=None, suelta=True):
    """La carta de un jugador: su PSD editable (y su TIFF suelto si no van todas en uno).
    Devuelve (archivos hechos, la carta en CMYK, su capa con la sombra para el TIFF con todos)."""
    carta, capas = componer(p, j, ajustes.get(j.id), clave, marca)
    nombre = productos.nombre_archivo(p, equipo, foto=j.nombre)
    carta_cmyk = color.a_cmyk(carta)
    hechos = [productos.guardar_raster(carta_cmyk, os.path.join(imp, nombre), "tif")] if suelta else []
    hechos.append(productos.guardar_psd(capas, tuple(p["lienzo"]), "CMYK", os.path.join(edi, nombre), carta_cmyk))
    # formato «capas»: [Fondo, Sombra, jugador, Corte y textos]; lo del medio es del jugador
    capa = _jugador_con_sombra(capas[1:-1]) if p.get("formato") == "capas" else None
    return hechos, carta_cmyk, capa

"""CARTAS: el jugador recortado se coloca en la carta.

El recorte y la colocación son los de la sesión CARTAS (carta_auto.py): el programa
recorta solo desde la foto arreglada, o usa el PNG del cliente si sube RECORTADAS. Ver
herramientas/preparar_carta.py para cómo se prepara la plantilla.

Colores de carta: la plantilla trae el diseño en el color de un club y, en «variantes»,
el mismo diseño en los colores de otros clubs (solo cambian el fondo, la línea dorada y
el ajuste de color del jugador). El nombre y el escudo del club se cambian por los que se
elijan en el programa: se quitan los de la plantilla y se ponen los nuevos.
"""
import os
import unicodedata

import cv2
import numpy as np
from PIL import Image

from . import color, productos
from .herramientas.preparar_carta import aplicar_lut

_cache = {}
_cache_club = {}
COLOR_PLANTILLA = "Amposta"   # el color con el que viene la plantilla (sin variante)


# --- colores de carta ----------------------------------------------------------

def _simple(texto):
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return "".join(ch for ch in t if ch.isalnum())


def colores(p):
    """[(clave, nombre)] de los colores de carta: None es el de la plantilla."""
    vs = sorted(p.get("variantes", {}).items(), key=lambda kv: _simple(kv[1]["nombre"]))
    return [(None, p.get("nombre_color", COLOR_PLANTILLA))] + [(k, v["nombre"]) for k, v in vs]


def color_para(p, nombre_escudo):
    """El color de carta que va con el escudo elegido (por su nombre), o None (el de la
    plantilla) si ninguno lo nombra."""
    n = _simple(nombre_escudo)
    if not n:
        return None
    for clave, v in p.get("variantes", {}).items():
        if any(_simple(b) in n for b in v.get("buscar", [])):
            return clave
    return None


def es_club_de_plantilla(p, nombre_escudo):
    """¿El escudo elegido es el del club de la plantilla (el de Amposta)?"""
    n = _simple(nombre_escudo)
    return bool(n) and any(_simple(b) in n for b in p.get("buscar", []))


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
            lut=np.load(os.path.join(c, p["lut"])),
            sombra=p["sombra"] if isinstance(p.get("sombra"), dict) else None,
        )
    return _cache[id_]


def _letra(fuentes, alto):
    """La primera letra que haya de 'fuentes', con mayúsculas de 'alto' px."""
    from PIL import ImageFont
    for nombre in fuentes:
        try:
            ruta = productos.ruta_fuente(nombre)
        except FileNotFoundError:
            continue
        f = ImageFont.truetype(ruta, 200)
        b = f.getbbox("H")
        return ImageFont.truetype(ruta, max(8, round(200 * alto / (b[3] - b[1]))))
    raise FileNotFoundError("No se encuentra la letra del nombre del club: " + ", ".join(fuentes))


def _nombre(info, texto, W):
    """El nombre del club como en la plantilla: misma altura de mayúsculas, centrado donde
    el original, ensanchado como la letra del diseño y con su degradado dorado por filas.
    Devuelve (imagen RGBA, x, y)."""
    from PIL import ImageDraw
    x0, y0, x1, y1 = info["caja"]
    alto = y1 - y0
    letra = _letra(info["fuentes"], alto)
    # cuánto hay que ensanchar esta letra para que el nombre escrito en la plantilla ocupe lo
    # que ocupaba (todas las plantillas de cartas traen «C.F. AMPOSTA»)
    b = letra.getbbox(info.get("original") or "C.F. AMPOSTA", anchor="ls")
    ancho_orig = b[2] - b[0]
    estira = (x1 - x0) / ancho_orig if ancho_orig else 1.0
    b = letra.getbbox(texto, anchor="ls")
    ancho = (b[2] - b[0]) * estira
    # nombres largos: más pequeño, sin pasarse del ancho de la franja del nombre
    maximo = min(W - 2 * x0 + (x1 - x0), 1.32 * (x1 - x0))
    k = min(1.0, maximo / ancho) if ancho else 1.0
    if k < 1:
        letra = _letra(info["fuentes"], alto * k)
        b = letra.getbbox(texto, anchor="ls")
    margen = 40
    lw, lh = b[2] - b[0] + 2 * margen, b[3] - b[1] + 2 * margen
    tinta = Image.new("L", (lw, lh), 0)
    ImageDraw.Draw(tinta).text((margen - b[0], margen - b[1]), texto, font=letra, fill=255, anchor="ls")
    nw = max(1, round(lw * estira))
    tinta = tinta.resize((nw, lh), Image.LANCZOS)
    # base de las letras en la de la plantilla (centrada en alto si es más pequeña)
    base_y = y1 - round(alto * (1 - k) / 2)
    alto_k = alto * k
    x = round((x0 + x1) / 2 - nw / 2)
    y = base_y - (margen - b[1])
    # el degradado: cada fila de las letras con el color de la misma altura en el original
    filas = np.asarray(info["degradado"], np.float32)
    yy = np.arange(lh) + y
    i = np.clip(np.round((yy - (base_y - alto_k)) / alto_k * (len(filas) - 1)), 0, len(filas) - 1).astype(int)
    rgb = np.repeat(filas[i][:, None, :], nw, axis=1)
    im = np.dstack([rgb, np.asarray(tinta, np.float32)]).astype(np.uint8)
    return Image.fromarray(im, "RGBA"), x, y


def fondo_club(p, clave=None, marca=None):
    """La carta sin jugador con el color 'clave' y el nombre y el escudo del club de
    'marca' ({escudo, club}). Devuelve (fondo HxWx3 float, capas para el PSD: Fondo y,
    si se cambian, Escudo y Nombre del club)."""
    t = _plantilla_px(p, clave)
    carpeta, info = _variante(p, clave)
    marca = marca or {}
    texto = (marca.get("club") or info.get("texto") or "").strip()
    escudo = marca.get("escudo")
    # en el color de la plantilla, su nombre y su escudo se quedan tal cual (los originales)
    cambia_nombre = bool(info.get("nombre")) and (clave is not None or _simple(texto) != _simple(info.get("texto")))
    cambia_escudo = bool(info.get("escudo")) and (clave is not None or bool(escudo))
    if not (cambia_nombre or cambia_escudo):
        return t["fondo"], [("Fondo", Image.fromarray(np.clip(t["fondo"] + .5, 0, 255).astype(np.uint8)), None, 0, 0)]
    id_ = (carpeta, os.path.getmtime(os.path.join(carpeta, p["fondo"])), texto if cambia_nombre else None,
           (escudo, os.path.getmtime(escudo)) if cambia_escudo and escudo else None)
    if id_ in _cache_club:
        return _cache_club[id_]
    W, H = p["lienzo"]
    limpio = t["fondo"].copy()
    extra = []
    for parte, cambia in (("escudo", cambia_escudo), ("nombre", cambia_nombre)):
        if not cambia:
            continue
        v = info[parte]["vacio"]
        hueco = np.asarray(Image.open(os.path.join(carpeta, v["archivo"])).convert("RGB"), np.float32)
        limpio[v["y"]:v["y"] + hueco.shape[0], v["x"]:v["x"] + hueco.shape[1]] = hueco
    if cambia_escudo and escudo:
        from .club import ajustado
        x0, y0, x1, y1 = info["escudo"]["caja"]
        extra.append(("Escudo", ajustado(escudo, (x1 - x0, y1 - y0)), x0, y0))
    if cambia_nombre and texto:
        im, x, y = _nombre(dict(info["nombre"], fuentes=info.get("fuentes", ["BebasNeue-Regular.ttf"])), texto, W)
        extra.append(("Nombre del club", im, x, y))
    fondo = limpio.copy()
    for _, im, x, y in extra:
        a = np.asarray(im, np.float32)
        h, w = a.shape[:2]
        xa, ya, xb, yb = max(0, x), max(0, y), min(W, x + w), min(H, y + h)
        if xb <= xa or yb <= ya:
            continue
        a = a[ya - y:yb - y, xa - x:xb - x]
        al = a[:, :, 3:4] / 255
        fondo[ya:yb, xa:xb] = a[:, :, :3] * al + fondo[ya:yb, xa:xb] * (1 - al)
    capas = [("Fondo", Image.fromarray(np.clip(limpio + .5, 0, 255).astype(np.uint8)), None, 0, 0)]
    capas += [(n, im, None, x, y) for n, im, x, y in extra]
    if len(_cache_club) > 2:
        _cache_club.clear()
    _cache_club[id_] = (fondo, capas)
    return fondo, capas


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
    kid = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    kid.paste(carta_auto.colocar(rec, med, col, ajuste), tuple(col["caja"][:2]))
    k = np.asarray(kid, np.float32)
    alfa = k[:, :, 3] / 255 * t["mascara"]
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
        jug = aplicar_lut(k[sl][:, :, :3], t["lut"])
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

    def una(j):
        if not getattr(j, "carta", None):
            progreso(f"  CARTAS: no se ha podido recortar a {j.nombre}, se salta")
            return []
        progreso(f"  CARTAS: {j.nombre}")
        return _una(p, j, equipo, ajustes, imp, edi, clave, marca)
    hechas = hilos.map(una, jugadores) if hilos else map(una, jugadores)
    return [s for h in hechas for s in h]


def _una(p, j, equipo, ajustes, imp, edi, clave=None, marca=None):
    carta, capas = componer(p, j, ajustes.get(j.id), clave, marca)
    nombre = productos.nombre_archivo(p, equipo, foto=j.nombre)
    carta_cmyk = color.a_cmyk(carta)
    return [productos.guardar_raster(carta_cmyk, os.path.join(imp, nombre), "tif"),
            productos.guardar_psd(capas, tuple(p["lienzo"]), "CMYK", os.path.join(edi, nombre), carta_cmyk)]

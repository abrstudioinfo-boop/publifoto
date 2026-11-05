"""CARTAS: el jugador recortado se coloca en la carta.

El recorte y la colocación son los de la sesión CARTAS (carta_auto.py): el programa
recorta solo desde la foto arreglada, o usa el PNG del cliente si sube RECORTADAS. Ver
herramientas/preparar_carta.py para cómo se prepara la plantilla.
"""
import os

import cv2
import numpy as np
from PIL import Image

from . import color, productos
from .herramientas.preparar_carta import aplicar_lut

_cache = {}


def _plantilla_px(p):
    # por carpeta y fecha: al actualizar la plantilla se vuelve a leer
    c = p["_carpeta"]
    clave = (c, os.path.getmtime(os.path.join(c, p["fondo"])))
    if clave not in _cache:
        _cache.clear()
        _cache[clave] = dict(
            fondo=np.asarray(Image.open(os.path.join(c, p["fondo"])).convert("RGB"), np.float32),
            debajo=np.asarray(Image.open(os.path.join(c, p["debajo"])).convert("RGB"), np.float32),
            mascara=np.asarray(Image.open(os.path.join(c, p["mascara"])), np.float32) / 255,
            encima=np.asarray(Image.open(os.path.join(c, p["encima"])), np.float32),
            lut=np.load(os.path.join(c, p["lut"])),
            sombra=np.load(os.path.join(c, p["sombra"])) if p.get("sombra") else None,
        )
    return _cache[clave]


def componer(p, jugador, ajuste=None):
    """Devuelve (carta RGB, capas para el PSD)."""
    t = _plantilla_px(p)
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
    carta = t["fondo"].copy()
    capas = [("Fondo", Image.fromarray(t["fondo"].astype(np.uint8)), None, 0, 0)]
    if len(ys):
        sombra = t["sombra"]
        m = len(sombra) - 1 if sombra is not None else 4
        # zona que se rehace: el jugador y su sombra alrededor (la de Photoshop)
        y0, y1 = max(0, ys.min() - m), min(H, ys.max() + 1 + m)
        x0, x1 = max(0, xs.min() - m), min(W, xs.max() + 1 + m)
        sl = (slice(y0, y1), slice(x0, x1))
        jug = aplicar_lut(k[sl][:, :, :3], t["lut"])
        a = alfa[sl][..., None]
        # lo que hay detrás del jugador: la propia carta sin el logo ni los textos (así no se
        # nota ningún borde donde se rehace); bajo el logo opaco, las capas de debajo
        e = t["encima"][sl]
        ea = e[:, :, 3:4] / 255
        limpio = (t["fondo"][sl] - e[:, :, :3] * ea) / np.maximum(1 - ea, 1e-3)
        bajo = np.where(ea > 0.98, t["debajo"][sl], np.clip(limpio, 0, 255))
        oscuro = None
        if sombra is not None:
            fuera = (alfa[sl] < 0.002).astype(np.uint8)
            d = cv2.distanceTransform(fuera, cv2.DIST_L2, 5)
            f = sombra[np.clip(np.round(d), 0, m).astype(int)]
            bajo = bajo * f[..., None]
            oscuro = (1 - f) * t["mascara"][sl]       # para la capa «Sombra» del PSD
        comp = jug * a + bajo * (1 - a)
        # lo que va encima (logo, textos) se vuelve a poner encima de todo
        comp = e[:, :, :3] * ea + comp * (1 - ea)
        # solo dentro del hueco de la foto; fuera, la carta tal cual
        mk = t["mascara"][sl][..., None]
        carta[sl] = comp * mk + carta[sl] * (1 - mk)
        cerca = alfa[sl] > 0.002
        if oscuro is not None and oscuro.max() > 0:
            # negro con esta opacidad = oscurecer el fondo como la sombra de Photoshop
            capas.append(("Sombra", Image.fromarray(np.dstack([np.zeros(oscuro.shape + (3,), np.uint8),
                                                               np.clip(oscuro * 255 + .5, 0, 255).astype(np.uint8)]),
                                                    "RGBA"), None, int(x0), int(y0)))
        jug_rgba = np.dstack([jug, alfa[sl] * 255]).astype(np.uint8)
        capas.append((jugador.nombre, Image.fromarray(np.clip(jug_rgba, 0, 255), "RGBA"), None, int(x0), int(y0)))
        enc = np.dstack([e[:, :, :3], ea[:, :, 0] * cerca * 255]).astype(np.uint8)
        if enc[:, :, 3].any():
            capas.append(("Logo y textos", Image.fromarray(enc, "RGBA"), None, int(x0), int(y0)))
    return Image.fromarray(np.clip(carta, 0, 255).astype(np.uint8)), capas


def generar(p, jugadores, equipo, ajustes, imp, edi, progreso=print, hilos=None):
    def una(j):
        if not getattr(j, "carta", None):
            progreso(f"  CARTAS: no se ha podido recortar a {j.nombre}, se salta")
            return []
        progreso(f"  CARTAS: {j.nombre}")
        return _una(p, j, equipo, ajustes, imp, edi)
    hechas = hilos.map(una, jugadores) if hilos else map(una, jugadores)
    return [s for h in hechas for s in h]


def _una(p, j, equipo, ajustes, imp, edi):
    carta, capas = componer(p, j, ajustes.get(j.id))
    nombre = productos.nombre_archivo(p, equipo, foto=j.nombre)
    carta_cmyk = color.a_cmyk(carta)
    return [productos.guardar_raster(carta_cmyk, os.path.join(imp, nombre), "tif"),
            productos.guardar_psd(capas, tuple(p["lienzo"]), "CMYK", os.path.join(edi, nombre), carta_cmyk)]

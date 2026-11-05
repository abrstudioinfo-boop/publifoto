"""CARTAS: el jugador ya recortado (PNG sin fondo) se coloca en la carta.

El programa no recorta: usa el PNG que sube el cliente. Ver
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
        )
    return _cache[clave]


def componer(p, jugador, ajuste=None):
    """Devuelve (carta RGB, capas para el PSD)."""
    t = _plantilla_px(p)
    W, H = p["lienzo"]
    kid = productos.foto_recortada(jugador, p, (W, H), ajuste, recorte=True)
    k = np.asarray(kid, np.float32)
    alfa = k[:, :, 3] / 255 * t["mascara"]
    zona = alfa > 0.002
    ys, xs = np.nonzero(zona)
    carta = t["fondo"].copy()
    capas = [("Fondo", Image.fromarray(t["fondo"].astype(np.uint8)), None, 0, 0)]
    if len(ys):
        y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
        sl = (slice(y0, y1), slice(x0, x1))
        jug = aplicar_lut(k[sl][:, :, :3], t["lut"])
        a = alfa[sl][..., None]
        comp = jug * a + t["debajo"][sl] * (1 - a)
        # lo que va encima (logo, textos) se vuelve a poner donde pasa el jugador
        cerca = cv2.dilate(zona[sl].astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        e = t["encima"][sl]
        ea = e[:, :, 3:4] / 255 * cerca[..., None]
        comp = e[:, :, :3] * ea + comp * (1 - ea)
        carta[sl] = np.where(cerca[..., None], comp, carta[sl])
        jug_rgba = np.dstack([jug, alfa[sl] * 255]).astype(np.uint8)
        capas.append((jugador.nombre, Image.fromarray(np.clip(jug_rgba, 0, 255), "RGBA"), None, int(x0), int(y0)))
        enc = np.dstack([e[:, :, :3], ea[:, :, 0] * 255]).astype(np.uint8)
        if enc[:, :, 3].any():
            capas.append(("Logo y textos", Image.fromarray(enc, "RGBA"), None, int(x0), int(y0)))
    return Image.fromarray(np.clip(carta, 0, 255).astype(np.uint8)), capas


def generar(p, jugadores, equipo, ajustes, imp, edi, progreso=print, hilos=None):
    def una(j):
        if not j.ruta_recorte:
            progreso(f"  CARTAS: falta el recorte de {j.nombre}, se salta")
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

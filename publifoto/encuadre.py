"""Encuadre de cada jugador dentro de un hueco de la plantilla.

Un encuadre se define con tres números, medidos sobre los trabajos ya aprobados:
  margen   -> qué parte del alto del hueco queda por encima de la cabeza
  alto_rel -> alto del hueco expresado en "alturas de cabeza" (pelo-cuello)
  centro   -> desplazamiento horizontal del centro del hueco respecto al jugador,
              en fracción del ancho del hueco (positivo = el jugador queda a la izquierda)
  referencia -> 'cara' (centrar en la cabeza) o 'mixto' (media de cara y tronco)
"""
from dataclasses import dataclass, asdict

from PIL import Image, ImageOps


@dataclass
class Encuadre:
    margen: float
    alto_rel: float
    centro: float = 0.0
    referencia: str = "mixto"


@dataclass
class Caja:
    """Recorte en píxeles de la foto original (puede salirse de la foto)."""
    x0: float
    y0: float
    x1: float
    y1: float

    def dict(self):
        return asdict(self)


def calcular(p, aspecto, enc, ajuste=None):
    """p: Puntos del análisis; aspecto: ancho/alto del hueco.
    ajuste: correcciones manuales {'dy','dx','zoom'} en fracción del hueco."""
    ajuste = ajuste or {}
    hc = p.alto_cabeza * p.alto
    alto = enc.alto_rel * hc / ajuste.get("zoom", 1.0)
    ancho = alto * aspecto
    y0 = p.cabeza * p.alto - enc.margen * alto
    ref = p.cara_x if enc.referencia == "cara" else (p.cara_x + p.cuerpo_x) / 2
    cx = ref * p.ancho + enc.centro * ancho
    cx -= ajuste.get("dx", 0.0) * ancho
    y0 -= ajuste.get("dy", 0.0) * alto
    return Caja(cx - ancho / 2, y0, cx + ancho / 2, y0 + alto)


def recortar(im, caja, tam):
    """Recorta la caja (aunque se salga de la foto, rellenando con el borde) y la
    escala a tam=(ancho, alto) px con calidad alta."""
    W, H = im.size
    x0, y0, x1, y1 = caja.x0, caja.y0, caja.x1, caja.y1
    pad_l, pad_t = max(0, -int(x0) + 1), max(0, -int(y0) + 1)
    pad_r, pad_b = max(0, int(x1) - W + 1), max(0, int(y1) - H + 1)
    if pad_l or pad_t or pad_r or pad_b:
        im = _rellenar(im, pad_l, pad_t, pad_r, pad_b)
        x0, x1 = x0 + pad_l, x1 + pad_l
        y0, y1 = y0 + pad_t, y1 + pad_t
    return im.resize(tam, Image.LANCZOS, box=(x0, y0, x1, y1))


def _rellenar(im, l, t, r, b):
    import numpy as np
    a = np.asarray(im)
    pads = ((t, b), (l, r)) + ((0, 0),) * (a.ndim - 2)
    if im.mode == "RGBA":
        return Image.fromarray(np.pad(a, pads, mode="constant"), im.mode)
    # como en los trabajos aprobados: el trozo que falta es el reflejo del borde
    # (estirar el último píxel deja rayas); si falta más que la foto entera, se estira
    H, W = a.shape[:2]
    refl = tuple((min(x, n - 1), min(y, n - 1)) for (x, y), n in zip(pads[:2], (H, W))) + pads[2:]
    a = np.pad(a, refl, mode="symmetric")
    resto = tuple((x - r[0], y - r[1]) for (x, y), r in zip(pads, refl))
    if any(v for par in resto for v in par):
        a = np.pad(a, resto, mode="edge")
    return Image.fromarray(a, im.mode)

"""Análisis de cada foto: silueta del jugador y puntos clave del cuerpo.

Se trabaja a baja resolución (lado largo 1024 px) y los resultados se dan en
fracciones de la foto original, así sirven para cualquier tamaño.
"""
import json
import os
import sys
from dataclasses import dataclass, asdict

import numpy as np
from PIL import Image, ImageOps

Image.MAX_IMAGE_PIXELS = None
LADO = 1024
_sesion = None


def _rembg():
    global _sesion
    if _sesion is None:
        # en el programa instalado el modelo va dentro: no se descarga nada
        modelos = os.path.join(os.path.dirname(__file__), "recursos", "modelos")
        if os.path.exists(os.path.join(modelos, "u2net_human_seg.onnx")):
            os.environ["U2NET_HOME"] = modelos
        from rembg import new_session
        _sesion = new_session("u2net_human_seg")
    return _sesion


@dataclass
class Puntos:
    ancho: int            # tamaño de la foto original
    alto: int
    cabeza: float         # y de lo alto del pelo (fracción del alto)
    cuello: float         # y del cuello
    cara_x: float         # centro de la cabeza (fracción del ancho)
    cuerpo_x: float       # centro del tronco
    pies: float           # y más baja de la silueta
    gris: float           # proporción de ropa gris (entrenadores)

    @property
    def alto_cabeza(self):
        return self.cuello - self.cabeza


def abrir(ruta):
    im = Image.open(ruta)
    return ImageOps.exif_transpose(im)


def mascara(im):
    from rembg import remove
    peq = im.convert("RGB")
    peq.thumbnail((LADO, LADO))
    m = remove(peq, session=_rembg(), only_mask=True)
    return np.asarray(m) > 127, peq


def analizar(ruta, cache=True):
    """Devuelve los Puntos de la foto (con caché en un .json al lado de la app;
    la silueta se guarda también, en un .png, para poder enderezar sin repetir rembg)."""
    ruta_cache = _ruta_cache(ruta)
    if cache and os.path.exists(ruta_cache) and os.path.exists(ruta_cache[:-5] + ".png"):
        with open(ruta_cache) as f:
            datos = json.load(f)
        campos = Puntos.__dataclass_fields__
        return Puntos(**{k: v for k, v in datos.items() if k in campos})
    im = abrir(ruta)
    m, peq = mascara(im)
    p = _puntos(m, np.asarray(peq), im.size)
    if cache:
        os.makedirs(os.path.dirname(ruta_cache), exist_ok=True)
        with open(ruta_cache, "w") as f:
            json.dump(asdict(p), f)
        Image.fromarray(m.astype(np.uint8) * 255).save(ruta_cache[:-5] + ".png")
    return p


_girados = {}


def girar(im, angulo):
    """Gira la foto 'angulo' grados (antihorario) sobre su centro, sin cambiar su
    tamaño. Las esquinas se rellenan con el reflejo del borde (o transparentes en
    los recortes PNG)."""
    import cv2
    if not angulo:
        return im
    a = np.asarray(im)
    H, W = a.shape[:2]
    M = cv2.getRotationMatrix2D((W / 2, H / 2), angulo, 1.0)
    borde = cv2.BORDER_CONSTANT if im.mode == "RGBA" else cv2.BORDER_REFLECT
    r = cv2.warpAffine(a, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=borde, borderValue=0)
    return Image.fromarray(r, im.mode)


def girada(ruta, p, angulo):
    """Puntos de la foto ya girada 'angulo' grados (misma silueta, girada)."""
    silueta = _ruta_cache(ruta)[:-5] + ".png"
    if not os.path.exists(silueta):
        # la foto ha cambiado desde que se analizó: se vuelve a analizar
        p = analizar(ruta)
    clave = (silueta, round(angulo, 2))
    if clave not in _girados:
        m = Image.open(silueta).convert("L")
        mg = np.asarray(girar(m, angulo)) > 127
        q = _puntos(mg, None, (p.ancho, p.alto))
        q.gris = p.gris
        _girados[clave] = q
    return _girados[clave]


def _ruta_cache(ruta):
    st = os.stat(ruta)
    clave = f"v2|{os.path.abspath(ruta)}|{st.st_size}|{int(st.st_mtime)}"
    import hashlib
    h = hashlib.md5(clave.encode()).hexdigest()
    return os.path.join(carpeta_cache(), h + ".json")


def carpeta_cache():
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Caches/Publifoto")
    return os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Publifoto", "cache")


def _puntos(m, rgb, tam):
    alto, ancho = m.shape
    filas = m.sum(1)
    ys = np.nonzero(filas > ancho * 0.01)[0]
    if len(ys) == 0:
        raise ValueError("No se ha encontrado a ninguna persona en la foto")
    # quedarse con la persona principal: columna con más silueta
    cols = m.sum(0)
    cx = int(np.argmax(np.convolve(cols, np.ones(51), "same")))
    cabeza = ys[0]
    # el cuello: fila más estrecha entre la cabeza y 1/3 del cuerpo
    anchos = []
    for y in range(cabeza, alto):
        xs = np.nonzero(m[y])[0]
        anchos.append(xs[-1] - xs[0] + 1 if len(xs) else 0)
    anchos = np.array(anchos, float)
    suav = np.convolve(anchos, np.ones(9) / 9, "same")
    maximo_cabeza = suav[: max(10, int(alto * 0.12))].max()
    busca = slice(int(alto * 0.04), int(alto * 0.30))
    tramo = suav[busca]
    # el cuello está donde, tras la cabeza, la anchura es mínima antes de los hombros
    hombros = np.nonzero(tramo > maximo_cabeza * 1.6)[0]
    fin = hombros[0] if len(hombros) else len(tramo)
    idx = int(np.argmin(tramo[:max(fin, 5)])) + busca.start
    cuello = cabeza + idx
    xs_cab = [np.nonzero(m[y])[0] for y in range(cabeza, cuello)]
    cara_x = np.mean([x.mean() for x in xs_cab if len(x)]) if xs_cab else cx
    tronco = m[cuello + int(idx * 0.5): cuello + int(idx * 2.0)]
    tx = np.nonzero(tronco.any(0))[0]
    cuerpo_x = (np.average(np.arange(ancho), weights=tronco.sum(0)) if tronco.sum() else cara_x)
    pies = ys[-1]
    # ropa gris (entrenadores): saturación baja dentro del tronco
    gris = 0.0
    if tronco.sum() and rgb is not None:
        zona = rgb[cuello + int(idx * 0.5): cuello + int(idx * 2.0)][tronco]
        mx, mn = zona.max(1).astype(int), zona.min(1).astype(int)
        lum = zona.mean(1)
        gris = float((((mx - mn) < 25) & (lum > 70) & (lum < 190)).mean())
    return Puntos(ancho=tam[0], alto=tam[1], cabeza=cabeza / alto, cuello=cuello / alto,
                  cara_x=cara_x / ancho, cuerpo_x=float(cuerpo_x) / ancho,
                  pies=pies / alto, gris=gris)

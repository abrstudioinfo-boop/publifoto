"""Retoque automático de la piel, como el pincel corrector del retocador.

Busca en la piel de la cara y del cuello los defectos que se notan (granos, rojeces,
heriditas, costras pequeñas) y los quita: el tono se rellena con la piel de alrededor y
la textura (poros) se copia de un trozo de piel limpia de al lado, así no queda una
mancha lisa. Las pecas y los lunares se dejan: son marrones, no rojos, y son de la persona.

Se mide sobre la foto arreglada a una escala fija (la cara a ANCHO_CARA px) y los
defectos se guardan en fracciones de la foto, así se aplican igual a la foto arreglada
y al recorte PNG de las cartas. Todo es local: nada sale del ordenador.
"""
import json
import os

import numpy as np
from PIL import Image

from .analisis import abrir, _ruta_cache

ANCHO_CARA = 600            # px de ancho de cara a los que se mide
VERSION = 2                 # súbelo al cambiar los umbrales: invalida la caché

# un defecto se quita si es claramente más rojo que la piel de alrededor: granos,
# rojeces, heriditas. Se mide en veces la variación normal del rojo en esa piel, así no
# depende de lo cálida que sea la foto. Lo oscuro y poco rojo (pecas, lunares, poros,
# pelos sueltos) se deja.
ROJO_SEMILLA = 5.0          # unidades a* de Lab sobre el fondo para empezar una mancha
ROJO_BORDE = 2.5            # hasta dónde llega la mancha
ROJO_MIN = 7.0              # rojez mínima (percentil 90 de la mancha) para tocarla...
ROJO_VECES = 6.0            # ...y al menos estas veces la variación de la piel
OSCURO_MAX = 12.0           # más oscura que esto respecto a la piel: lunar o sombra, se deja
DIAM_MIN = 0.006            # tamaños en fracción del ancho de la cara
DIAM_MAX = 0.05
HUECO = 1.35                # radio que se rehace, en radios de la mancha
TONO = 1.0                  # suavizado del tono de alrededor, en radios
MAX_DEFECTOS = 25           # como mucho, los más notables


def _indices(conexiones):
    return sorted({i for par in conexiones for i in par})


def _mascara_piel(forma, pts, mp):
    """Piel de la cara: el óvalo sin ojos, cejas, labios ni orificios de la nariz."""
    import cv2
    fm = mp.solutions.face_mesh
    m = np.zeros(forma, np.uint8)
    ovalo = pts[_indices(fm.FACEMESH_FACE_OVAL)]
    cv2.fillConvexPoly(m, cv2.convexHull(ovalo.astype(np.int32)), 255)
    ancho = np.ptp(ovalo[:, 0])
    quitar = np.zeros(forma, np.uint8)
    for conj, margen in ((fm.FACEMESH_LEFT_EYE, 0.035), (fm.FACEMESH_RIGHT_EYE, 0.035),
                         (fm.FACEMESH_LEFT_EYEBROW, 0.03), (fm.FACEMESH_RIGHT_EYEBROW, 0.03),
                         (fm.FACEMESH_LIPS, 0.02)):
        h = cv2.convexHull(pts[_indices(conj)].astype(np.int32))
        cv2.fillConvexPoly(quitar, h, 255)
    # ojo + ceja como un bloque (pestañas, sombra del párpado)
    for ojo, ceja in ((fm.FACEMESH_LEFT_EYE, fm.FACEMESH_LEFT_EYEBROW),
                      (fm.FACEMESH_RIGHT_EYE, fm.FACEMESH_RIGHT_EYEBROW)):
        h = cv2.convexHull(pts[_indices(ojo) + _indices(ceja)].astype(np.int32))
        cv2.fillConvexPoly(quitar, h, 255)
    # orificios de la nariz y su sombra
    for i in (98, 327):
        cv2.circle(quitar, tuple(int(v) for v in pts[i]), int(ancho * 0.035), 255, -1)
    k = max(3, int(ancho * 0.03)) | 1
    quitar = cv2.dilate(quitar, np.ones((k, k), np.uint8))
    m[quitar > 0] = 0
    # el borde del óvalo (pelo, orejas, fondo) no cuenta
    m = cv2.erode(m, np.ones((k, k), np.uint8))
    return m > 0, ancho


def _malla(im, caja):
    """Puntos de la malla de la cara (px de 'im') o None."""
    from . import marcas
    _, malla, _ = marcas._modelos()
    r = marcas._malla_en(im, caja, 1.8, 768, malla)
    if r is None:
        return None
    P, ox, oy, sw, sh = r
    return np.array([[ox + l.x * sw, oy + l.y * sh] for l in P], np.float32)


def _fondo(canal, piel, k):
    """Valor de la piel de alrededor en cada punto (mediana grande, solo con piel)."""
    import cv2
    # lo que no es piel se rellena con la media de la piel cercana, para que los ojos o
    # el pelo no tiren de la mediana en los bordes
    w = piel.astype(np.float32)
    s = max(3, k * 2) | 1
    num = cv2.GaussianBlur(canal * w, (s, s), 0)
    den = cv2.GaussianBlur(w, (s, s), 0)
    relleno = np.where(piel, canal, num / np.maximum(den, 1e-3))
    lo, hi = float(relleno.min()), float(relleno.max())
    u8 = np.clip((relleno - lo) / max(hi - lo, 1e-3) * 255, 0, 255).astype(np.uint8)
    med = cv2.medianBlur(u8, k).astype(np.float32) / 255 * (hi - lo) + lo
    return med


def detectar_imagen(im, caja_cara, info=None):
    """Defectos de la piel de 'im' (PIL RGB). Devuelve [[x, y, radio], ...] en fracciones
    del ancho/alto de la foto (el radio en fracción del ancho)."""
    import cv2
    from . import marcas
    W, H = im.size
    pts = _malla(im, caja_cara)
    if pts is None:
        if info is not None:
            info["motivo"] = "sin malla"
        return []
    mp = marcas._importar_mediapipe()
    ovalo = pts[_indices(mp.solutions.face_mesh.FACEMESH_FACE_OVAL)]
    ancho = float(np.ptp(ovalo[:, 0]))
    if ancho < 60:
        return []
    # recorte de la cara con margen, escalado a ANCHO_CARA
    x0, y0 = ovalo.min(0) - ancho * 0.1
    x1, y1 = ovalo.max(0) + ancho * 0.1
    x0, y0 = max(0, int(x0)), max(0, int(y0))
    x1, y1 = min(W, int(x1)), min(H, int(y1))
    esc = ANCHO_CARA / ancho
    rec = im.crop((x0, y0, x1, y1)).convert("RGB")
    rec = rec.resize((max(1, round((x1 - x0) * esc)), max(1, round((y1 - y0) * esc))), Image.LANCZOS)
    a = np.asarray(rec, np.float32) / 255
    piel, _ = _mascara_piel(a.shape[:2], (pts - [x0, y0]) * esc, mp)
    if piel.sum() < 1000:
        return []
    lab = cv2.cvtColor(a, cv2.COLOR_RGB2LAB)
    L, A = lab[:, :, 0], lab[:, :, 1]
    k = int(ANCHO_CARA * DIAM_MAX * 1.6) | 1
    dL = L - _fondo(L, piel, k)
    dA = A - _fondo(A, piel, k)
    rojo = dA
    variacion = max(float(np.std(dA[piel])), 0.5)
    semilla = piel & (rojo > ROJO_SEMILLA)
    zona = piel & (rojo > ROJO_BORDE)
    n, etq, est, _ = cv2.connectedComponentsWithStats(zona.astype(np.uint8), connectivity=8)
    con_semilla = np.zeros(n, bool)
    con_semilla[np.unique(etq[semilla])] = True
    dmin, dmax = DIAM_MIN * ANCHO_CARA, DIAM_MAX * ANCHO_CARA
    defectos = []
    motivos = {}
    for i in range(1, n):
        if not con_semilla[i]:
            continue
        motivos["candidatos"] = motivos.get("candidatos", 0) + 1
        x, y, w, h, area = est[i]
        diam = 2 * np.sqrt(area / np.pi)
        if not dmin <= diam <= dmax or max(w, h) > dmax * 1.3:
            motivos["tamaño"] = motivos.get("tamaño", 0) + 1
            continue
        sel = etq[y:y + h, x:x + w] == i
        # que no sea un trozo del borde de la piel (labio, ojera, sombra de la nariz)
        alrededor = cv2.dilate(sel.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        if piel[y:y + h, x:x + w][alrededor].mean() < 0.9:
            motivos["borde"] = motivos.get("borde", 0) + 1
            continue
        rojez = float(np.percentile(rojo[y:y + h, x:x + w][sel], 90))
        oscuro = -float(np.percentile(dL[y:y + h, x:x + w][sel], 10))
        if info is not None:
            info.setdefault("todos", []).append((round(diam / ANCHO_CARA, 4), round(rojez, 1), round(oscuro, 1)))
        if rojez < max(ROJO_MIN, ROJO_VECES * variacion) or oscuro > OSCURO_MAX:
            motivos["poco"] = motivos.get("poco", 0) + 1
            continue
        contraste = rojez
        ys, xs = np.nonzero(sel)
        r = max(np.ptp(xs), np.ptp(ys)) / 2 + 1.5
        defectos.append([(x0 + (x + xs.mean()) / esc) / W, (y0 + (y + ys.mean()) / esc) / H,
                         r / esc / W, contraste])
    if info is not None:
        info.update(motivos, piel=int(piel.sum()), ancho=round(ancho),
                    sd=round(variacion, 2))
    defectos.sort(key=lambda d: -d[3])
    return [[round(v, 6) for v in d[:3]] for d in defectos[:MAX_DEFECTOS]]


def detectar(ruta, caja_cara, cache=True):
    ruta_cache = _ruta_cache(ruta)[:-5] + f"_retoque{VERSION}.json"
    if cache and os.path.exists(ruta_cache):
        with open(ruta_cache) as f:
            return json.load(f)
    d = detectar_imagen(abrir(ruta).convert("RGB"), caja_cara) if caja_cara else []
    if cache:
        os.makedirs(os.path.dirname(ruta_cache), exist_ok=True)
        with open(ruta_cache, "w") as f:
            json.dump(d, f)
    return d


def _curar(a, cx, cy, r, alfa=None):
    """Quita una mancha de radio r (px) centrada en (cx, cy) del array float 'a' (H, W, 3)."""
    import cv2
    H, W = a.shape[:2]
    R = int(np.ceil(r * 5)) + 4
    x0, y0, x1, y1 = max(0, int(cx) - R), max(0, int(cy) - R), min(W, int(cx) + R + 1), min(H, int(cy) + R + 1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return
    sub = a[y0:y1, x0:x1]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    d = np.hypot(xx - cx, yy - cy)
    hueco = d <= r * HUECO
    sig = max(1.0, r * 0.6)
    baja = cv2.GaussianBlur(sub, (0, 0), sig)
    alta = sub - baja
    # tono: la media de la piel de alrededor, sin contar la mancha
    fuera = (~hueco).astype(np.float32)
    s_t = max(1.0, r * TONO)
    tono = cv2.GaussianBlur(sub * fuera[..., None], (0, 0), s_t) /         np.maximum(cv2.GaussianBlur(fuera, (0, 0), s_t), 1e-4)[..., None]
    tono = np.where(hueco[..., None], tono, baja)
    # textura (poros): la de un trozo de piel de al lado, el más parecido en tono y con
    # una textura como la de alrededor (no una ceja, un pelo o el borde de la nariz)
    anillo = (d > r * 1.6) & (d <= r * 2.6)
    ref = float(np.std(alta[anillo])) if anillo.any() else 0.0
    mejor = None
    for paso in (3.0, 4.0):
        for ang in np.linspace(0, 2 * np.pi, 12, endpoint=False):
            dx, dy = int(round(np.cos(ang) * r * paso)), int(round(np.sin(ang) * r * paso))
            M = np.float32([[1, 0, dx], [0, 1, dy]])
            dona = cv2.warpAffine(alta, M, (sub.shape[1], sub.shape[0]), flags=cv2.INTER_NEAREST,
                                  borderMode=cv2.BORDER_REFLECT)
            base = cv2.warpAffine(baja, M, (sub.shape[1], sub.shape[0]), flags=cv2.INTER_NEAREST,
                                  borderMode=cv2.BORDER_REFLECT)
            if alfa is not None:
                af = cv2.warpAffine(alfa[y0:y1, x0:x1], M, (sub.shape[1], sub.shape[0]),
                                    flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_REFLECT)
                if af[hueco].min() < 0.99:
                    continue
            sd = float(np.std(dona[hueco]))
            if ref and not 0.6 * ref <= sd <= 1.6 * ref:
                continue
            dif = float(np.abs(base[hueco] - tono[hueco]).mean())
            if mejor is None or dif < mejor[0]:
                mejor = (dif, dona)
    textura = mejor[1] if mejor is not None else alta * 0.3
    nuevo = tono + np.where(hueco[..., None], textura, alta)
    # mezcla suave: dentro del hueco todo nuevo, hacia fuera se funde con la foto
    peso = np.clip((r * (HUECO + 0.6) - d) / max(r * 0.6, 1.0), 0, 1)[..., None]
    sub[:] = sub * (1 - peso) + nuevo * peso


def aplicar(im, defectos):
    """Devuelve 'im' (PIL RGB o RGBA, del tamaño de la foto arreglada) con los defectos
    quitados. Solo se trabaja en el trozo de cada mancha: la foto entera no se toca."""
    if not defectos:
        return im
    W, H = im.size
    modo = im.mode
    a = np.array(im)
    for x, y, r in defectos:
        cx, cy, rr = x * W, y * H, r * W
        R = int(np.ceil(rr * 5)) + 6
        x0, y0, x1, y1 = max(0, int(cx) - R), max(0, int(cy) - R), min(W, int(cx) + R + 1), min(H, int(cy) + R + 1)
        if x1 <= x0 or y1 <= y0:
            continue
        trozo = a[y0:y1, x0:x1].astype(np.float32) / 255
        rgb = np.ascontiguousarray(trozo[:, :, :3])
        alfa = trozo[:, :, 3] if modo == "RGBA" else None
        _curar(rgb, cx - x0, cy - y0, rr, alfa)
        a[y0:y1, x0:x1, :3] = np.clip(rgb * 255 + 0.5, 0, 255).astype(np.uint8)
    return Image.fromarray(a, modo)


# --- dentro del programa -------------------------------------------------------

def preparar_jugador(j):
    """Busca los defectos de la piel de un jugador ya analizado (con sus marcas).
    Devuelve avisos: si falla, la foto sale sin retocar pero no se para nada."""
    from .revision import Aviso
    m = j.marcas
    j.retoque = []
    if m is None or not m.cara or m.caras != 1 or not m.caja_cara:
        return []
    try:
        j.retoque = detectar(j.ruta, m.caja_cara)
    except Exception as e:
        return [Aviso(j.id, "retoque", "revisar", f"No se ha podido revisar la piel ({e}): sale sin retocar.")]
    if not j.retoque:
        return []
    n = len(j.retoque)
    return [Aviso(j.id, "retoque", "corregido",
                  f"Piel: {n} {'grano o rojez quitado' if n == 1 else 'granos o rojeces quitados'}.")]


def activo(jugador):
    return bool(jugador.retoque) and getattr(jugador, "retocar", True) and not getattr(jugador, "sin_retoque", False)


def de_jugador(jugador, im):
    """La foto (arreglada o recorte) con la piel retocada, si toca. Nunca falla: si algo va
    mal, devuelve la foto tal cual."""
    if not activo(jugador):
        return im
    try:
        return aplicar(im, jugador.retoque)
    except Exception as e:
        print(f"Retoque de piel de {jugador.id} no aplicado: {e}")
        return im

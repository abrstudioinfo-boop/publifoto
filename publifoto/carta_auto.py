"""CARTAS sin recortes hechos a mano: el recorte del jugador y su sitio en la carta,
igual que la sesión CARTAS (sus scripts prep_waist, metrics, pose, hem y bire_matte).

- Colocación (colocar): se mide en la silueta recortada lo alto del pelo, el cuello, el
  centro de la cabeza y del tronco, y los hombros y las caderas (MediaPipe). Todos con el
  pelo a la misma altura y cortados por la cintura, donde empieza el pantalón (como la
  carta aprobada de S11 B): a cada uno se le da el tamaño para que su cintura caiga en la
  línea dorada. Los números de la carta (caja de la foto, pelo, corte, centro, cintura)
  están en la plantilla, en "colocacion".
- Recorte (recortar): el modelo de retrato BiRefNet (local, sin internet) en la foto
  arreglada, y el pelo como la sesión: alfa fino con el filtro guiado y color de los
  mechones sin el tono de la pared (bire_matte).

Todo es local: las fotos no salen del ordenador.
"""
import json
import os

import numpy as np
from PIL import Image

from .analisis import abrir, _ruta_cache

Image.MAX_IMAGE_PIXELS = None
VERSION = 1
REGLA = 2   # regla de colocación: al cambiarla se vuelve a medir sin volver a recortar

# los de la sesión CARTAS para la plantilla de 2026 (3780 x 5315)
COLOCACION = {"caja": [430, 600, 3350, 3189], "pelo": 820, "corte": 3189, "centro": 1930.0, "cabeza": 794,
              "cintura": 0.97}


# --- medidas de la silueta (metrics.py de la sesión) --------------------------

def medidas(al, thr=128):
    m = al > thr
    w = m.sum(1).astype(float)
    k = 15
    ws = np.convolve(w, np.ones(k) / k, mode='same')
    rows = np.where(w > 0)[0]
    top = int(rows[0])
    mx = 0
    y = top
    narrowing = False
    mxy = top
    while y < len(ws):
        if ws[y] > mx and not narrowing:
            mx = ws[y]
            mxy = y
        if mx > 200 and ws[y] < 0.85 * mx:
            narrowing = True
        if narrowing and ws[y] > 1.3 * mx:
            break
        y += 1
    neck = mxy + int(np.argmin(ws[mxy:y]))
    cols = [np.where(m[r])[0] for r in range(top, neck)]
    cx = float(np.mean([(c[0] + c[-1]) / 2 for c in cols if len(c)]))
    # centro del tronco: de cuello + 0,5 cabezas a cuello + 1,5 cabezas
    hl = neck - top
    tc = [np.where(m[r])[0] for r in range(neck + hl // 2, min(len(w), neck + int(1.5 * hl)))]
    tcx = float(np.mean([(c[0] + c[-1]) / 2 for c in tc if len(c)]))
    return dict(top=top, neck=int(neck), headlen=int(hl), headw=float(mx), cx=cx, torso_cx=tcx)


# --- hombros y caderas (pose.py de la sesión) ----------------------------------

_pose = None


def _modelo_pose():
    # una instancia propia con los ajustes de la sesión (no la de marcas.py, que busca
    # con otra confianza sobre la foto entera)
    global _pose
    if _pose is None:
        from .marcas import _importar_mediapipe
        mp = _importar_mediapipe()
        _pose = mp.solutions.pose.Pose(static_image_mode=True, model_complexity=2, enable_segmentation=False)
    return _pose


def puntos_cuerpo(rgba):
    """rgba: el recorte (PIL RGBA, tamaño de la foto). Hombros, caderas... en px."""
    bg = Image.new('RGB', rgba.size, (128, 128, 128))
    bg.paste(rgba, (0, 0), rgba)
    sc = 1600 / max(bg.size)
    small = bg.resize((int(bg.size[0] * sc), int(bg.size[1] * sc)))
    res = _modelo_pose().process(np.asarray(small))
    if not res.pose_landmarks:
        return None
    L = res.pose_landmarks.landmark
    W, H = rgba.size
    g = lambda i: (L[i].x * W, L[i].y * H, L[i].visibility)
    return dict(ls=g(11), rs=g(12), lh=g(23), rh=g(24), lk=g(25), rk=g(26), le=g(13), re=g(14), lw=g(15), rw=g(16))


# --- colocación (prep_waist.py de la sesión) -----------------------------------

def medir_colocacion(rgba, col=None):
    """Escala y anclas del jugador en la carta, medidas en su recorte (PIL RGBA).
    Devuelve dict(s, mid, top, como)."""
    col = col or COLOCACION
    arr = np.array(rgba)
    m = medidas(arr[..., 3])
    lm = puntos_cuerpo(rgba)
    tope, corte = col["pelo"], col["corte"]
    if lm:
        sy = (lm['ls'][1] + lm['rs'][1]) / 2
        hy = (lm['lh'][1] + lm['rh'][1]) / 2
        # cintura = donde empieza el pantalón: a 0,97 de hombros a caderas (medido en la
        # carta aprobada; la búsqueda del bajo de la camiseta fallaba en varios jugadores)
        waist = sy + col.get("cintura", 0.97) * (hy - sy)
        s = (corte - tope) / (waist - m['top'])
        como = 'pose'
    else:
        s = col["cabeza"] / m['headlen']
        como = 'head'
    return dict(s=float(s), mid=0.5 * (m['cx'] + m['torso_cx']), top=float(m['top']), como=como)


def colocar(rgba, med, col=None, ajuste=None):
    """El recorte (PIL RGBA) en la caja de la foto de la carta: imagen RGBA del tamaño de
    la caja. ajuste: {dx, dy, zoom} de la revisión rápida, en fracción de la caja."""
    col = col or COLOCACION
    ajuste = ajuste or {}
    bx0, by0, bx1, by1 = col["caja"]
    bw, bh = bx1 - bx0, by1 - by0
    s = med["s"] * ajuste.get("zoom", 1.0)
    x0 = med["mid"] - (col["centro"] - bx0) / s
    y0 = med["top"] - (col["pelo"] - by0) / s
    x0 -= ajuste.get("dx", 0.0) * bw / s
    y0 -= ajuste.get("dy", 0.0) * bh / s
    rect = (x0, y0, x0 + bw / s, y0 + bh / s)
    return rgba.convert('RGBa').transform((bw, bh), Image.EXTENT, rect, Image.BICUBIC).convert('RGBA')


# --- recorte -------------------------------------------------------------------

MODELO_RETRATO = "birefnet-portrait.onnx"
_retrato = None


def ruta_modelo():
    """El modelo BiRefNet de retrato: dentro del programa, o el que deja rembg en ~/.rembg.
    rembg lo baja a <carpeta>/models/birefnet-portrait/, así que se mira también ahí."""
    modelos = os.path.join(os.path.dirname(__file__), "recursos", "modelos")
    casa = os.path.join(os.path.expanduser("~"), ".rembg")
    for base in (modelos, casa):
        for ruta in (os.path.join(base, MODELO_RETRATO),
                     os.path.join(base, "models", "birefnet-portrait", MODELO_RETRATO)):
            if os.path.exists(ruta):
                return ruta
    return os.path.join(casa, "models", "birefnet-portrait", MODELO_RETRATO)


def _sesion_retrato():
    global _retrato
    if _retrato is None:
        import onnxruntime as ort
        _retrato = ort.InferenceSession(ruta_modelo(), providers=["CPUExecutionProvider"])
    return _retrato


def liberar_modelo():
    """El modelo ocupa casi 1 GB: se suelta al acabar de recortar."""
    global _retrato
    _retrato = None


def alfa_retrato(rgb):
    """Alfa BiRefNet-portrait de un trozo (uint8 HxWx3) -> float HxW (bire.py de la sesión)."""
    import cv2
    s = _sesion_retrato()
    h, w = rgb.shape[:2]
    x = cv2.resize(rgb, (1024, 1024), interpolation=cv2.INTER_AREA).astype(np.float32) / 255
    x = (x - [0.485, 0.456, 0.406]) / [0.229, 0.224, 0.225]
    x = x.transpose(2, 0, 1)[None].astype(np.float32)
    o = s.run(None, {s.get_inputs()[0].name: x})[0][0, 0]
    o = 1 / (1 + np.exp(-o))
    return cv2.resize(o, (w, h), interpolation=cv2.INTER_CUBIC).clip(0, 1)


def filtro_guiado(I, p, r, eps):
    """El filtro guiado de OpenCV (ximgproc) si está; si no, el mismo en numpy (en color)."""
    import cv2
    if hasattr(cv2, "ximgproc"):
        return cv2.ximgproc.guidedFilter(I, p, r, eps)
    I = I.astype(np.float32) / 255
    p = p.astype(np.float32)
    box = lambda x: cv2.boxFilter(x, -1, (2 * r + 1, 2 * r + 1))
    mI, mp_ = box(I), box(p)
    cov = box(I * p[..., None]) - mI * mp_[..., None]
    var = np.empty(I.shape[:2] + (3, 3), np.float32)
    for i in range(3):
        for j in range(i, 3):
            var[..., i, j] = var[..., j, i] = box(I[..., i] * I[..., j]) - mI[..., i] * mI[..., j]
    var += eps * np.eye(3, dtype=np.float32)
    a = np.linalg.solve(var, cov[..., None])[..., 0]
    b = mp_ - (a * mI).sum(-1)
    return (box(a) * I).sum(-1) + box(b)


def _extender(rgb, w, sigmas=(4, 12, 36, 100, 300)):
    """Color de 'rgb' donde w=1, extendido hacia fuera (spread de matte2.py de la sesión)."""
    import cv2
    out = np.zeros_like(rgb)
    lleno = np.zeros(w.shape, bool)
    for s in sigmas:
        num = cv2.GaussianBlur(rgb * w[..., None], (0, 0), s)
        den = cv2.GaussianBlur(w, (0, 0), s)
        ok = (den > 1e-3) & ~lleno
        out[ok] = num[ok] / den[ok, None]
        lleno |= ok
    return out


def pelo(rgba, J, pecho=0.7, fundido=160):
    """El pelo como la sesión (bire_matte.py): alfa de retrato BiRefNet de la foto hasta el
    pecho, fundido con el recorte del cuerpo; los mechones finos con el color del pelo,
    sin el brillo de la pared. rgba: recorte (uint8 HxWx4); J: foto (uint8 HxWx3)."""
    import cv2
    from pymatting import estimate_foreground_ml
    ua = rgba[..., 3]
    m = medidas(ua)
    top, neck = m["top"], m["neck"]
    yc = min(ua.shape[0] - 1, neck + int(pecho * (neck - top)))
    y0 = max(0, top - 200)
    y1 = min(ua.shape[0], yc + fundido + 20)
    xs = np.where(ua[y0:y1].max(0) > 0)[0]
    x0 = max(0, xs[0] - 200)
    x1 = min(ua.shape[1], xs[-1] + 200)
    I = np.ascontiguousarray(J[y0:y1, x0:x1])
    ba = alfa_retrato(I).astype(np.float32)
    ba = np.clip(filtro_guiado(I, ba, 6, 1e-4), 0, 1)
    ba[ba < 0.02] = 0
    a = ua[y0:y1, x0:x1].astype(np.float32) / 255
    yy = np.arange(I.shape[0])[:, None]
    w = np.clip((yc - y0 + fundido - yy) / fundido, 0, 1) * np.ones_like(a)
    na = ba * w + a * (1 - w)
    fg = estimate_foreground_ml(I / 255.0, na.astype(np.float64))
    nucleo = ((na > 0.97) & (cv2.erode((na > 0.97).astype(np.uint8), np.ones((9, 9), np.uint8)) > 0)).astype(np.float32)
    F = _extender(I.astype(np.float32), nucleo)
    fgL = cv2.cvtColor(np.clip(fg * 255, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    FL = cv2.cvtColor(np.clip(F, 0, 255).astype(np.uint8), cv2.COLOR_RGB2LAB).astype(np.float32)
    k = np.sqrt(np.clip(na, 0, 1))[..., None]
    ab = fgL[..., 1:] * k + FL[..., 1:] * (1 - k)
    d = ab - FL[..., 1:]
    n = np.sqrt((d ** 2).sum(2, keepdims=True)) + 1e-3
    fgL[..., 1:] = FL[..., 1:] + d * np.minimum(1, 12 / n)
    bajo = na < 0.6
    fgL[..., 0] = np.where(bajo, np.minimum(fgL[..., 0], FL[..., 0] + 18), fgL[..., 0])
    fg = cv2.cvtColor(np.clip(fgL, 0, 255).astype(np.uint8), cv2.COLOR_LAB2RGB)
    res = rgba.copy()
    sub = res[y0:y1, x0:x1]
    upd = (w > 0.01) & (na > 0) & (na < 0.999)
    sub[..., :3][upd] = fg[upd]
    sub[..., 3] = np.clip(na * 255 + .5, 0, 255).astype(np.uint8)
    return res


def alfa_cuerpo(J, silueta):
    """Alfa del cuerpo: BiRefNet de retrato en la persona entera (recortada con margen).
    Medido contra los recortes del usuario: coincide el 97 % del contorno a 3 px. Pasarlo
    solo por la mitad de arriba, a más resolución, salió peor (el empalme con las piernas).
    J: foto uint8 HxWx3; silueta: máscara bool del análisis (baja resolución)."""
    H, W = J.shape[:2]
    ys, xs = np.nonzero(silueta)
    f = W / silueta.shape[1]
    x0, x1, y0, y1 = xs.min() * f, xs.max() * f, ys.min() * f, ys.max() * f
    mx, my = 0.06 * (x1 - x0), 0.03 * (y1 - y0)
    x0, y0 = max(0, int(x0 - mx)), max(0, int(y0 - my))
    x1, y1 = min(W, int(x1 + mx)), min(H, int(y1 + my))
    a = np.zeros((H, W), np.float32)
    a[y0:y1, x0:x1] = alfa_retrato(np.ascontiguousarray(J[y0:y1, x0:x1]))
    return a


def _huella(jugador):
    origen = jugador.ruta_recorte or ""
    return [os.path.getmtime(jugador.ruta), origen, os.path.getmtime(origen) if origen else 0]


def en_cache(jugador):
    """(PNG, colocación) si el recorte de la carta ya está hecho y sirve; si no, None."""
    png, js = rutas_cache(jugador)
    if not (os.path.exists(png) and os.path.exists(js)):
        return None
    try:
        with open(js) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    if d.get("huella") != _huella(jugador):
        return None
    if d.get("regla") != REGLA:
        d["colocacion"], d["regla"] = medir_colocacion(Image.open(png).convert("RGBA")), REGLA
        with open(js, "w") as f:
            json.dump(d, f)
    return png, d["colocacion"]


def rutas_cache(jugador):
    base = _ruta_cache(jugador.ruta)[:-5] + f"_carta{VERSION}"
    return base + ".png", base + ".json"


def preparar(jugador, cache=True):
    """El recorte del jugador para la carta (PNG en la caché) y su colocación.
    Con el recorte del cliente (RECORTADAS) se hace como la sesión: su cuerpo y el pelo
    con el modelo de retrato; si no, el cuerpo también lo recorta el modelo.
    Devuelve (ruta del PNG, colocación)."""
    png, js = rutas_cache(jugador)
    origen = jugador.ruta_recorte or ""
    huella = _huella(jugador)
    hecho = en_cache(jugador) if cache else None
    if hecho:
        return hecho
    J = np.asarray(abrir(jugador.ruta).convert("RGB"))
    if origen:
        cuerpo = np.asarray(abrir(origen).convert("RGBA"))
        if cuerpo.shape[:2] != J.shape[:2]:
            cuerpo = np.asarray(Image.fromarray(cuerpo).resize((J.shape[1], J.shape[0]), Image.LANCZOS))
    else:
        from .analisis import mascara
        sil, _ = mascara(Image.fromarray(J))
        a = alfa_cuerpo(J, sil)
        cuerpo = np.dstack([J, np.clip(a * 255 + .5, 0, 255).astype(np.uint8)])
    # la colocación se mide en el cuerpo (como la sesión, en el recorte del usuario)
    med = medir_colocacion(Image.fromarray(cuerpo))
    final = pelo(cuerpo, J)
    os.makedirs(os.path.dirname(png), exist_ok=True)
    Image.fromarray(final).save(png)
    with open(js, "w") as f:
        json.dump({"huella": huella, "colocacion": med, "regla": REGLA}, f)
    return png, med

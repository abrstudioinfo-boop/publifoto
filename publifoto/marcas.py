"""Puntos de la cara y del cuerpo con MediaPipe (modelos incluidos en el paquete,
funcionan sin internet).

Sirven a los revisores automáticos (revision.py) para enderezar a los jugadores
torcidos, comprobar los encuadres y distinguir a los adultos de los niños.
Todo se da en fracciones de la foto original.
"""
import json
import math
import os
from dataclasses import dataclass, asdict, field

import numpy as np
from PIL import Image

from .analisis import abrir, _ruta_cache

LADO = 1024
_pose = None
_malla = None
_caras = None


def _importar_mediapipe():
    # MediaPipe importa matplotlib solo para sus funciones de dibujo, que aquí no se
    # usan. Si matplotlib está roto o le falta algo (p. ej. dateutil), se sustituye por
    # un módulo vacío para que no tumbe la carga de las fotos.
    # Se prueba antes de cargar MediaPipe: su parte nativa no se puede cargar dos veces.
    import sys
    import types
    try:
        import matplotlib.pyplot  # noqa: F401
    except Exception:
        for nombre in [n for n in sys.modules if n.startswith("matplotlib")]:
            del sys.modules[nombre]
        falso = types.ModuleType("matplotlib")
        falso.pyplot = types.ModuleType("matplotlib.pyplot")
        sys.modules["matplotlib"] = falso
        sys.modules["matplotlib.pyplot"] = falso.pyplot
    import mediapipe as mp
    return mp


def _modelos():
    global _pose, _malla, _caras
    if _pose is None:
        mp = _importar_mediapipe()
        _pose =mp.solutions.pose.Pose(static_image_mode=True, model_complexity=2,
                                       min_detection_confidence=0.3)
        _malla = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1,
                                                 refine_landmarks=True,
                                                 min_detection_confidence=0.3)
        _caras = mp.solutions.face_detection.FaceDetection(model_selection=1,
                                                          min_detection_confidence=0.4)
    return _pose, _malla, _caras


@dataclass
class Marcas:
    cara: bool = False                 # se ha encontrado la malla de la cara
    caras: int = 0                     # número de caras en la foto
    ojo_izq: list = field(default_factory=list)   # [x, y] ojo a la izquierda de la foto
    ojo_der: list = field(default_factory=list)
    frente: list = field(default_factory=list)    # punto alto de la frente (malla 10)
    barbilla: list = field(default_factory=list)  # malla 152
    caja_cara: list = field(default_factory=list) # x0, y0, x1, y1
    pose: bool = False
    hombro_izq: list = field(default_factory=list)  # a la izquierda de la foto
    hombro_der: list = field(default_factory=list)
    cadera_izq: list = field(default_factory=list)
    cadera_der: list = field(default_factory=list)
    vis_hombros: float = 0.0
    vis_caderas: float = 0.0
    iris_ipd: float = 0.0              # diámetro del iris / distancia entre pupilas (más alto en niños)
    apertura_ojos: float = 0.0         # alto/ancho del ojo (baja con los ojos cerrados)

    def girada(self, angulo, W, H):
        """Las mismas marcas sobre la foto girada 'angulo' grados (antihorario) sobre su centro."""
        if not angulo:
            return self
        a = math.radians(angulo)
        c, s = math.cos(a), math.sin(a)

        def g(pt):
            if not pt:
                return pt
            x, y = pt[0] * W - W / 2, pt[1] * H - H / 2
            # en la imagen la y crece hacia abajo: giro antihorario visible
            return [(x * c + y * s + W / 2) / W, (-x * s + y * c + H / 2) / H]

        d = asdict(self)
        for k in ("ojo_izq", "ojo_der", "frente", "barbilla", "hombro_izq", "hombro_der",
                  "cadera_izq", "cadera_der"):
            d[k] = g(d[k])
        if self.caja_cara:
            x0, y0, x1, y1 = self.caja_cara
            esquinas = [g([x0, y0]), g([x1, y0]), g([x0, y1]), g([x1, y1])]
            d["caja_cara"] = [min(e[0] for e in esquinas), min(e[1] for e in esquinas),
                              max(e[0] for e in esquinas), max(e[1] for e in esquinas)]
        return Marcas(**d)

    # ángulos en grados; positivo = la línea baja hacia la derecha de la foto,
    # es decir, hay que girar la foto ese ángulo en sentido antihorario para enderezarla
    def _ang(self, a, b, W, H):
        return math.degrees(math.atan2((b[1] - a[1]) * H, (b[0] - a[0]) * W))

    def angulo_ojos(self, W, H):
        return self._ang(self.ojo_izq, self.ojo_der, W, H) if self.cara else None

    def angulo_hombros(self, W, H):
        return self._ang(self.hombro_izq, self.hombro_der, W, H) if self.pose else None

    def angulo_eje(self, W, H):
        """Inclinación del tronco (de la cadera a los hombros) respecto a la vertical."""
        if not self.pose or self.vis_caderas < 0.5:
            return None
        h = np.mean([self.hombro_izq, self.hombro_der], 0)
        c = np.mean([self.cadera_izq, self.cadera_der], 0)
        return math.degrees(math.atan2((h[0] - c[0]) * W, (c[1] - h[1]) * H))

    def angulo_cara(self, W, H):
        """Inclinación de la línea frente-barbilla respecto a la vertical."""
        if not self.cara:
            return None
        f, b = self.frente, self.barbilla
        return math.degrees(math.atan2((f[0] - b[0]) * W, (b[1] - f[1]) * H))


def _xy(l, ox, oy, sw, sh, W, H):
    return [(ox + l.x * sw) / W, (oy + l.y * sh) / H]


def medir(ruta, cache=True):
    ruta_cache = _ruta_cache(ruta)[:-5] + "_marcas2.json"
    if cache and os.path.exists(ruta_cache):
        with open(ruta_cache) as f:
            datos = json.load(f)
        campos = Marcas.__dataclass_fields__
        return Marcas(**{k: v for k, v in datos.items() if k in campos})
    im = abrir(ruta).convert("RGB")
    m = medir_imagen(im)
    if cache:
        os.makedirs(os.path.dirname(ruta_cache), exist_ok=True)
        with open(ruta_cache, "w") as f:
            json.dump(asdict(m), f)
    return m


def medir_imagen(im):
    pose, malla, caras = _modelos()
    peq = im.copy()
    peq.thumbnail((LADO, LADO))
    a = np.ascontiguousarray(np.asarray(peq))
    H, W = a.shape[:2]
    m = Marcas()
    r = pose.process(a)
    if r.pose_landmarks:
        P = r.pose_landmarks.landmark
        m.pose = True
        # en MediaPipe 11/23 son el hombro/cadera izquierdos de la persona (derecha de la foto)
        m.hombro_izq, m.hombro_der = [P[12].x, P[12].y], [P[11].x, P[11].y]
        m.cadera_izq, m.cadera_der = [P[24].x, P[24].y], [P[23].x, P[23].y]
        m.vis_hombros = float(min(P[11].visibility, P[12].visibility))
        m.vis_caderas = float(min(P[23].visibility, P[24].visibility))
    d = caras.process(a)
    m.caras = len(d.detections) if d.detections else 0
    # la malla se busca en un recorte alrededor de la cabeza (las caras son pequeñas
    # en una foto de cuerpo entero), a resolución completa
    caja = None
    if d.detections:
        b = max(d.detections, key=lambda x: x.score[0]).location_data.relative_bounding_box
        caja = (b.xmin, b.ymin, b.xmin + b.width, b.ymin + b.height)
    elif m.pose:
        P = r.pose_landmarks.landmark
        xs = [P[i].x for i in range(11)]
        ys = [P[i].y for i in range(11)]
        cx, cy = np.mean(xs), np.mean(ys)
        lado = max(0.05, (max(xs) - min(xs)) * 1.6)
        caja = (cx - lado / 2, cy - lado / 2, cx + lado / 2, cy + lado / 2)
    if caja:
        Wo, Ho = im.size
        rr = _malla_en(im, caja, 2.2, 640, malla)
        if rr:
            L, ox, oy, sw, sh = rr
            p = lambda i: _xy(L[i], ox, oy, sw, sh, Wo, Ho)
            m.cara = True
            m.ojo_izq = list(np.mean([p(33), p(133)], 0))
            m.ojo_der = list(np.mean([p(362), p(263)], 0))
            m.frente, m.barbilla = p(10), p(152)
            d = lambda a, b: math.hypot((L[a].x - L[b].x) * sw, (L[a].y - L[b].y) * sh)
            m.apertura_ojos = float(np.mean([d(159, 145) / max(1e-6, d(33, 133)),
                                             d(386, 374) / max(1e-6, d(362, 263))]))
            xs = [L[i].x for i in range(468)]
            ys = [L[i].y for i in range(468)]
            m.caja_cara = [(ox + min(xs) * sw) / Wo, (oy + min(ys) * sh) / Ho,
                           (ox + max(xs) * sw) / Wo, (oy + max(ys) * sh) / Ho]
            # el iris se mide en un recorte más cerrado, a más resolución
            ri = _malla_en(im, m.caja_cara, 1.8, 768, malla)
            if ri:
                Li = ri[0]
                q = lambda i: np.array([Li[i].x * 768, Li[i].y * 768])
                iris = [np.mean([np.linalg.norm(q(c) - q(k)) for k in anillo]) * 2
                        for c, anillo in ((468, (469, 470, 471, 472)), (473, (474, 475, 476, 477)))]
                ipd = np.linalg.norm(q(468) - q(473))
                if ipd > 0:
                    m.iris_ipd = float(np.mean(iris) / ipd)
    for k in ("ojo_izq", "ojo_der", "frente", "barbilla", "caja_cara"):
        setattr(m, k, [float(v) for v in getattr(m, k)])
    return m


def _malla_en(im, caja, factor, lado_max, malla):
    """Malla de la cara en un recorte cuadrado alrededor de 'caja' (fracciones)."""
    Wo, Ho = im.size
    x0, y0, x1, y1 = caja
    lado = max((x1 - x0) * Wo, (y1 - y0) * Ho) * factor
    cx, cy = (x0 + x1) / 2 * Wo, (y0 + y1) / 2 * Ho
    ox, oy = max(0, int(cx - lado / 2)), max(0, int(cy - lado / 2))
    rec = im.crop((ox, oy, min(Wo, int(cx + lado / 2)), min(Ho, int(cy + lado / 2))))
    sw, sh = rec.size
    if sw < 20 or sh < 20:
        return None
    if lado_max == 768:
        rec = rec.resize((768, 768), Image.LANCZOS)
    elif max(sw, sh) > lado_max:
        rec = rec.resize((round(sw * lado_max / max(sw, sh)), round(sh * lado_max / max(sw, sh))), Image.LANCZOS)
    rr = malla.process(np.ascontiguousarray(np.asarray(rec)))
    if not rr.multi_face_landmarks:
        return None
    return rr.multi_face_landmarks[0].landmark, ox, oy, sw, sh

"""Prepara la plantilla de CARTAS desde el TIFF con capas de Photoshop.

La carta tiene formas vectoriales con efectos (marco dorado, flechas) que no
guardan píxeles, así que no se recompone capa a capa. Se aprovecha la imagen
final que guarda el propio TIFF y solo se rehace la zona del jugador:
  - debajo: capas con píxeles que van por debajo del jugador (fondo oscuro)
  - mascara: máscara de "Place Your Image Here" (dónde se ve el jugador)
  - lut: ajuste de color de Photoshop (Corrección selectiva + Brillo/Contraste)
    aprendido comparando las capas con la imagen final
  - encima: capas con píxeles por encima del jugador (logo, textos, separadores)
"""
import json
import os
import sys

import cv2
import numpy as np
import tifffile
from PIL import Image

from .preparar_plantillas import DESTINO, _guardar
from .tiff_capas import leer_capas

Image.MAX_IMAGE_PIXELS = None
HUECO = "Place Your Image Here"
N_LUT = 17
SOMBRA_MAX = 120   # px


def visibilidad(capas):
    """Visibilidad efectiva teniendo en cuenta los grupos (orden de abajo arriba)."""
    pila, grupos = [], []
    for i, c in enumerate(capas):
        if c["seccion"] == 3:
            pila.append([])
        elif c["seccion"] in (1, 2):
            hijos = pila.pop() if pila else []
            grupos.append((i, hijos))
            if pila:
                pila[-1] += [i] + hijos
        elif pila:
            pila[-1].append(i)
    vis = [c["visible"] for c in capas]
    for g, hijos in grupos:
        if not capas[g]["visible"]:
            for h in hijos:
                vis[h] = False
    return vis


def _sobre(fondo, capa, x, y, opacidad=1.0):
    """Compone una capa RGBA sobre un lienzo RGB float (in situ)."""
    a = np.asarray(capa, np.float32)
    H, W = fondo.shape[:2]
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(W, x + a.shape[1]), min(H, y + a.shape[0])
    if x1 <= x0 or y1 <= y0:
        return
    t = a[y0 - y:y1 - y, x0 - x:x1 - x]
    al = t[:, :, 3:4] / 255 * opacidad
    fondo[y0:y1, x0:x1] = t[:, :, :3] * al + fondo[y0:y1, x0:x1] * (1 - al)


def ajustar_lut(antes, despues, n=N_LUT):
    """LUT 3D (n^3) que lleva los colores 'antes' a 'despues' (arrays Nx3 0..255)."""
    idx = np.clip(np.round(antes / 255 * (n - 1)).astype(int), 0, n - 1)
    plano = idx[:, 0] * n * n + idx[:, 1] * n + idx[:, 2]
    suma = np.zeros((n ** 3, 3))
    cuenta = np.zeros(n ** 3)
    np.add.at(suma, plano, despues)
    np.add.at(cuenta, plano, 1)
    # celdas vacías: identidad + desplazamiento medio
    eje = np.linspace(0, 255, n)
    ident = np.stack(np.meshgrid(eje, eje, eje, indexing="ij"), -1).reshape(-1, 3)
    desplaz = (despues - antes).mean(0)
    lut = ident + desplaz
    hay = cuenta >= 3
    lut[hay] = suma[hay] / cuenta[hay][:, None]
    return np.clip(lut, 0, 255).reshape(n, n, n, 3).astype(np.float32)


def aplicar_lut(rgb, lut):
    """Interpolación trilineal. rgb: HxWx3 float 0..255."""
    n = lut.shape[0]
    p = np.clip(rgb / 255 * (n - 1), 0, n - 1 - 1e-6)
    i = p.astype(int)
    f = p - i
    out = np.zeros_like(rgb, dtype=np.float32)
    for dr in (0, 1):
        for dg in (0, 1):
            for db in (0, 1):
                w = ((f[..., 0] if dr else 1 - f[..., 0]) * (f[..., 1] if dg else 1 - f[..., 1])
                     * (f[..., 2] if db else 1 - f[..., 2]))
                out += w[..., None] * lut[i[..., 0] + dr, i[..., 1] + dg, i[..., 2] + db]
    return out


def main(ruta_tif, id_="cartas"):
    (W, H), modo, capas = leer_capas(ruta_tif)
    vis = visibilidad(capas)
    k = next(i for i, c in enumerate(capas) if c["nombre"] == HUECO)
    hueco = capas[k]
    final = tifffile.imread(ruta_tif)[:, :, :3].astype(np.float32)

    debajo = np.zeros((H, W, 3), np.float32)
    cubierto = np.zeros((H, W), np.float32)
    for i in range(k):
        c = capas[i]
        if vis[i] and "imagen" in c and c["seccion"] == 0:
            l, t, _, _ = c["caja"]
            _sobre(debajo, c["imagen"], l, t, c["opacidad"] / 255)
            a = np.zeros((H, W), np.float32)
            al = np.asarray(c["imagen"])[:, :, 3] / 255
            x0, y0 = max(0, l), max(0, t)
            x1, y1 = min(W, l + al.shape[1]), min(H, t + al.shape[0])
            a[y0:y1, x0:x1] = al[y0 - t:y1 - t, x0 - l:x1 - l]
            cubierto = a + cubierto * (1 - a)

    # máscara del hueco en coordenadas del lienzo
    m = hueco["mascara"]
    ml, mt, mr, mb = m["caja"]
    mascara = np.full((H, W), m["defecto"], np.uint8)
    mascara[max(0, mt):min(H, mb), max(0, ml):min(W, mr)] = \
        m["imagen"][max(0, -mt):min(H, mb) - mt, max(0, -ml):min(W, mr) - ml]

    # jugador de ejemplo (para aprender el ajuste de color)
    ej = np.zeros((H, W, 4), np.float32)
    l, t, r, b = hueco["caja"]
    ej[t:b, l:r] = np.asarray(hueco["imagen"], np.float32)
    ej_a = ej[:, :, 3] / 255 * mascara / 255
    antes = ej[:, :, :3] * ej_a[..., None] + debajo * (1 - ej_a[..., None])

    # capas por encima con píxeles
    encima = np.zeros((H, W, 4), np.float32)
    lista_encima = []
    for i in range(k + 1, len(capas)):
        c = capas[i]
        if vis[i] and "imagen" in c and c["seccion"] == 0:
            lista_encima.append(c["nombre"])
            l, t, _, _ = c["caja"]
            lienzo = np.zeros((H, W, 3), np.float32)
            _sobre(lienzo, c["imagen"], l, t)
            a = np.zeros((H, W), np.float32)
            al = np.asarray(c["imagen"])[:, :, 3] / 255 * c["opacidad"] / 255
            x0, y0 = max(0, l), max(0, t)
            x1, y1 = min(W, l + al.shape[1]), min(H, t + al.shape[0])
            a[y0:y1, x0:x1] = al[y0 - t:y1 - t, x0 - l:x1 - l]
            encima[:, :, :3] = lienzo * a[..., None] + encima[:, :, :3] * (1 - a[..., None])
            encima[:, :, 3] = a + encima[:, :, 3] * (1 - a)

    # aprender el ajuste donde el resultado no lleva nada encima
    zona = (mascara > 250) & (cubierto > 0.99) & (encima[:, :, 3] < 0.01)
    lut = ajustar_lut(antes[zona], final[zona])
    error = np.abs(aplicar_lut(antes[zona][None], lut)[0] - final[zona]).mean()
    print("error medio del ajuste de color:", round(float(error), 2), "niveles de 255")

    # sombra que Photoshop pone alrededor del jugador: oscurecimiento según la
    # distancia al borde de la silueta, medido junto al jugador de ejemplo
    base = aplicar_lut(debajo, lut)
    fuera = (ej_a < 0.002).astype(np.uint8)
    dist = cv2.distanceTransform(fuera, cv2.DIST_L2, 5)
    perfil = np.ones(SOMBRA_MAX + 1, np.float32)
    lum_f, lum_b = final.mean(2), base.mean(2) + 1
    libre = (mascara > 250) & (encima[:, :, 3] < 0.01)
    for d in range(SOMBRA_MAX + 1):
        z = libre & (dist > d - 0.5) & (dist <= d + 0.5)
        if z.sum() > 50:
            perfil[d] = float(np.median(lum_f[z] / lum_b[z]))
    perfil = np.clip(np.maximum.accumulate(np.minimum(perfil, 1.0)), 0, 1)
    print("sombra: oscurece", round(1 - float(perfil[1]), 3), "junto al borde")

    # carta sin jugador: el resultado final con la zona del ejemplo rehecha
    sin = final.copy()
    rehacer = (dist <= SOMBRA_MAX) & (mascara > 0)
    sin[rehacer] = base[rehacer]
    ea = encima[:, :, 3:4]
    sin = np.where(rehacer[..., None], encima[:, :, :3] * ea + sin * (1 - ea), sin)

    carpeta = os.path.join(DESTINO, id_)
    os.makedirs(carpeta, exist_ok=True)
    Image.fromarray(np.clip(sin, 0, 255).astype(np.uint8)).save(os.path.join(carpeta, "fondo.png"))
    Image.fromarray(np.clip(base, 0, 255).astype(np.uint8)).save(os.path.join(carpeta, "debajo.png"))
    Image.fromarray(mascara).save(os.path.join(carpeta, "mascara.png"))
    Image.fromarray(np.dstack([np.clip(encima[:, :, :3], 0, 255), encima[:, :, 3:] * 255]).astype(np.uint8),
                    "RGBA").save(os.path.join(carpeta, "encima.png"))
    np.save(os.path.join(carpeta, "lut.npy"), lut)
    np.save(os.path.join(carpeta, "sombra.npy"), perfil)
    _guardar(id_, {
        "id": id_, "nombre": "CARTAS", "tipo": "carta", "color": "CMYK", "lienzo": [W, H], "ppp": 300,
        "fondo": "fondo.png", "debajo": "debajo.png", "mascara": "mascara.png", "encima": "encima.png",
        "lut": "lut.npy", "sombra": "sombra.npy", "capas_encima": lista_encima,
        "huecos": [{"rect": [0, 0, W, H]}], "jugadores_por_hoja": 1,
        # medido en las cartas aprobadas: pelo al 14,75 % del alto de la carta
        "encuadre": {"margen": 0.1475, "alto_rel": 5.69, "centro": 0.0, "referencia": "mixto"},
        "impresion": ["tif"], "editable": "psd", "archivo": "CARTA {FOTO}",
        "excluir": ["entrenador", "equipo"], "necesita_recorte": True,
    })


if __name__ == "__main__":
    main(sys.argv[1])

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
# sombra del jugador como la de Photoshop: la silueta crecida (px) y difuminada (sigma, px),
# oscureciendo el fondo hasta «fuerza». Comparada con la carta aprobada de Amposta (S11 B),
# un poco más suave a petición del usuario.
SOMBRA = {"crece": 25, "difumina": 30, "fuerza": 0.33}
# letra del nombre del club cuando se cambia: la del diseño (DIN Pro Condensed Bold) si está
# en el ordenador; si no, Bebas Neue (libre, va con el programa)
FUENTES_CLUB = ["DINPro-CondensedBold.otf", "DINPro-CondBold.otf", "BebasNeue-Regular.ttf"]


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


def _linea(final, debajo, encima, corte, margen=40):
    """Añade a «encima» la línea dorada que corta al jugador (cerca de la fila del corte).
    Devuelve la primera fila de la línea."""
    y0 = max(0, corte - margen)
    z = final[y0:corte + margen]
    # dorado: rojo y verde altos y poco azul (en las cartas de fondo rojo el verde es bajo)
    oro = (z[..., 0] > 120) & (z[..., 1] > 80) & (z[..., 0] - z[..., 2] > 50)
    filas = np.nonzero(oro.mean(1) > 0.3)[0]
    if not len(filas):
        return None
    a, b = y0 + filas.min(), y0 + filas.max()
    centro = (a + b) // 2
    # el tramo seguido más largo (a los lados la fila toca el marco dorado)
    cols = np.nonzero(oro[centro - y0])[0]
    tramos = np.split(cols, np.nonzero(np.diff(cols) > 5)[0] + 1)
    t = max(tramos, key=len)
    x0, x1 = t.min(), t.max() + 1
    # en las filas del borde, cuánto tapa la línea (medido contra lo que hay debajo)
    nucleo = final[centro, x0:x1]
    for y in range(a - 3, b + 4):
        if a <= y <= b:
            al = np.ones(x1 - x0, np.float32)
        else:
            num = (final[y, x0:x1] - debajo[y, x0:x1]).sum(1)
            den = (nucleo - debajo[y, x0:x1]).sum(1)
            ok = np.abs(den) > 30
            if not ok.any():
                continue
            al = np.full(x1 - x0, np.clip(np.median(num[ok] / den[ok]), 0, 1), np.float32)
        col = final[y, x0:x1] if a <= y <= b else nucleo
        e = encima[y, x0:x1]
        sale = al + e[:, 3] * (1 - al)
        e[:, :3] = (col * al[:, None] + e[:, :3] * (e[:, 3] * (1 - al))[:, None]) / np.maximum(sale, 1e-6)[:, None]
        e[:, 3] = sale
    print("línea dorada: filas", a, "a", b, "columnas", x0, "a", x1)
    return a


def _rellenar(img, mask, caja):
    """El fondo que hay debajo de una forma (mask) dentro de caja: rayas verticales (un valor
    por columna) más un degradado vertical (uno por fila), aprendidos en lo que se ve
    alrededor, y lo que no explican (rayas en diagonal) traído suave desde los bordes.
    Devuelve el recorte de caja ya rellenado."""
    x0, y0, x1, y1 = caja
    z = img[y0:y1, x0:x1].astype(np.float32)
    m = mask[y0:y1, x0:x1]
    k = ~m
    zz = np.where(k[..., None], z, np.nan)
    R = np.zeros((y1 - y0, 3), np.float32)
    for _ in range(4):
        C = np.nanmedian(zz - R[:, None], axis=0)
        R = np.nanmedian(zz - C[None], axis=1)
    pred = R[:, None] + C[None]
    resto = np.where(k[..., None], z - pred, 0).astype(np.float32)
    num = cv2.GaussianBlur(resto, (0, 0), 10)
    den = cv2.GaussianBlur(k.astype(np.float32), (0, 0), 10)[..., None]
    pred = np.clip(pred + num / np.maximum(den, 1e-2), 0, 255)
    suave = np.maximum(cv2.GaussianBlur(m.astype(np.float32), (0, 0), 1.5), m)[..., None]
    return np.clip(pred * suave + z * (1 - suave), 0, 255)


def _erf(x):
    # Abramowitz y Stegun 7.1.26 (error < 1,5e-7): sin depender de scipy
    t = 1 / (1 + 0.3275911 * np.abs(x))
    y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t \
        * np.exp(-x * x)
    return np.sign(x) * y


def _sombra_bajo_linea(fondo, linea_capa, texto_alfa):
    """Bajo la línea dorada la plantilla trae la sombra del jugador de ejemplo (un
    rectángulo oscuro y difuminado, en el centro). El jugador tiene que salir de la línea
    sin sombra debajo: se mide esa sombra (rectángulo difuminado ajustado a lo que oscurece
    respecto al recuadro del nombre más abajo, donde no llega) y se quita. Las letras del
    nombre van por encima de la sombra y no se tocan. Cambia fondo y devuelve cuánto
    oscurecía (0 si no había)."""
    ys, xs = np.nonzero(linea_capa[:, :, 3] > 0.5)
    if not len(ys):
        return 0.0
    y0, x0, x1 = int(ys.max()) + 4, int(xs.min()), int(xs.max()) + 1
    ty = np.nonzero(texto_alfa.max(1) > 0.5)[0] if texto_alfa is not None else []
    ref0 = int(ty.max()) + 12 if len(ty) else y0 + 320       # bajo el nombre: sin sombra
    y1 = min(ref0 - 10, y0 + 300)
    Z = fondo[y0:y1, x0:x1]
    ref = fondo[ref0:ref0 + 30, x0:x1].mean(0)
    r = Z.mean(2) / np.maximum(ref.mean(1)[None], 1)
    letras = texto_alfa[y0:y1, x0:x1] > 0.02 if texto_alfa is not None else np.zeros(r.shape, bool)
    ok = (r < 1.15) & (r > 0.3) & ~letras
    yy, xx = np.mgrid[0:y1 - y0, 0:x1 - x0].astype(np.float64)

    def modelo(q, X, Y):
        A, xa, xb, sx, yb, sy = q
        return 1 - A * 0.5 * (_erf((X - xa) / sx) - _erf((X - xb) / sx)) * 0.5 * (1 - _erf((Y - yb) / sy))
    # ajuste (Levenberg-Marquardt) en una de cada 4 filas y columnas
    X, Y, R, K = (v[::4, ::4].ravel() for v in (xx, yy, r, ok))
    X, Y, R = X[K], Y[K], R[K]
    w = x1 - x0
    q = np.array([0.4, 0.3 * w, 0.7 * w, 30.0, 60.0, 30.0])
    lam = 1e-2
    err = np.sum((modelo(q, X, Y) - R) ** 2)
    for _ in range(80):
        J = np.empty((len(R), 6))
        for i in range(6):
            d = np.zeros(6)
            d[i] = 1e-4 * max(1.0, abs(q[i]))
            J[:, i] = (modelo(q + d, X, Y) - modelo(q - d, X, Y)) / (2 * d[i])
        g = J.T @ (modelo(q, X, Y) - R)
        H = J.T @ J
        paso = -np.linalg.solve(H + lam * np.diag(np.diag(H) + 1e-9), g)
        nuevo = q + paso
        nuevo[3], nuevo[5] = max(nuevo[3], 2), max(nuevo[5], 2)
        e2 = np.sum((modelo(nuevo, X, Y) - R) ** 2)
        if e2 < err:
            q, err, lam = nuevo, e2, lam * 0.3
        else:
            lam *= 5
    A = float(q[0])
    if A < 0.05 or q[1] >= q[2]:
        return 0.0
    Sm = modelo(q, xx, yy).astype(np.float32)
    peso = np.clip((1 - Sm) / A, 0, 1)
    c1 = Z / np.maximum(Sm, 0.2)[..., None]
    # lo que queda, por canal y suave, solo donde había sombra
    # (en los fondos rojos o verdes algún canal es casi 0: ahí no se corrige más)
    valido = (ref >= 8)[None]
    r2 = np.where(valido, c1 / np.maximum(ref[None], 1), 1).astype(np.float32)
    k = (ok & (peso > 0.02)).astype(np.float32)
    lejos = ok & (peso < 0.02)
    base = np.array([np.median(r2[..., c][lejos]) if lejos.any() else 1.0 for c in range(3)], np.float32)
    base = np.where(np.isfinite(base) & (base > 0.05), base, 1).astype(np.float32)
    num = cv2.GaussianBlur(r2 * k[..., None], (0, 0), 20)
    den = cv2.GaussianBlur(k, (0, 0), 20)[..., None]
    resto = np.where(den > 0.05, num / np.maximum(den, 1e-3), base) / base
    resto = np.where(valido, np.clip(resto, 0.5, 2), 1)
    c2 = c1 / (1 + (resto - 1) * peso[..., None])
    a = texto_alfa[y0:y1, x0:x1, None] if texto_alfa is not None else 0
    fondo[y0:y1, x0:x1] = np.clip(c2, 0, 255) * (1 - a) + Z * a
    return A


def _club(capas, final, fondo, W, H):
    """Nombre del club y escudo de la plantilla: dónde están, el degradado del texto y el
    fondo que queda al quitarlos (para poner los de otro club)."""
    def capa(nombre):
        c = next((c for c in capas if c["nombre"] == nombre and "imagen" in c), None)
        if c is None:
            return None, None
        l, t, r, b = c["caja"]
        a = np.zeros((H, W), np.float32)
        al = np.asarray(c["imagen"])[:, :, 3] / 255
        x0, y0, x1, y1 = max(0, l), max(0, t), min(W, r), min(H, b)
        a[y0:y1, x0:x1] = al[y0 - t:y1 - t, x0 - l:x1 - l]
        return a, (x0, y0, x1, y1)
    datos, vacios = {}, {}
    for clave, nombre, crece, margen in (("nombre", "TEXT CLUB", 2, 40), ("escudo", "logo", 8, 60)):
        a, caja = capa(nombre)
        if a is None:
            continue
        ys, xs = np.nonzero(a > 0.5)
        tinta = [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1]
        forma = cv2.dilate((a > 0.012).astype(np.uint8),
                           cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * crece + 1, 2 * crece + 1))) > 0
        l, t, r, b = caja
        zona = (max(0, l - margen), max(0, t - margen), min(W, r + margen), min(H, b + margen))
        vacios[clave] = (zona, _rellenar(fondo, forma, zona))
        datos[clave] = {"caja": tinta}
        if clave == "nombre":
            # color de cada fila de las letras (el degradado dorado es un efecto de la capa)
            lleno = a > 0.95
            filas = [[int(round(v)) for v in np.median(final[y][lleno[y]], 0)] if lleno[y].any() else None
                     for y in range(tinta[1], tinta[3])]
            for i in range(len(filas)):          # filas sin letras llenas: la más cercana
                if filas[i] is None:
                    filas[i] = next(f for f in filas[i:] + filas[::-1] if f is not None)
            datos[clave]["degradado"] = filas
    return datos, vacios


def _color_aprobado(final, ruta_aprobada, mascara, ej_a):
    """Ajuste de color (afín) que lleva la imagen de la plantilla a una carta aprobada del
    mismo diseño: Photoshop evalúa los ajustes en CMYK al pasarla y el gris sale neutro, no
    morado. Se aprende en el fondo, lejos de los dos jugadores; vale también para el jugador."""
    from ..color import a_rgb
    ap = np.asarray(a_rgb(Image.open(ruta_aprobada)), np.float32)
    if ap.shape != final.shape:
        raise ValueError("La carta aprobada no tiene el tamaño de la plantilla.")
    # el jugador de la carta aprobada: lo que cambia mucho respecto a la plantilla
    sil = ((np.abs(ap - final).max(2) > 45) & (mascara > 128)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(sil)
    if n > 1:
        sil = (lab == 1 + np.argmax(st[1:, 4])).astype(np.uint8)
    sil = cv2.morphologyEx(sil, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    jugadores = np.maximum(sil, (ej_a > 0.002).astype(np.uint8))
    lejos = cv2.distanceTransform(1 - jugadores, cv2.DIST_L2, 5) > 150
    a, b = final[lejos][::5], ap[lejos][::5]
    F = np.column_stack([a / 255, np.ones(len(a))])
    M = np.linalg.lstsq(F, b, rcond=None)[0]
    print("color de la carta aprobada: diferencia", round(float(np.abs(a - b).mean()), 2), "->",
          round(float(np.abs(F @ M - b).mean()), 2), "niveles de 255")
    return M


def _afin(rgb, M):
    return np.clip(rgb / 255 @ M[:3] + M[3], 0, 255).astype(np.float32)


def _construir(ruta_tif, aprobada=None):
    """Lo que la carta necesita sacado del TIFF con capas: el fondo sin el jugador de
    ejemplo, la máscara, la línea dorada, el ajuste de color del jugador, y el nombre y el
    escudo del club. aprobada: una carta final ya aprobada de este diseño (CMYK); si se
    da, la plantilla toma su color."""
    (W, H), modo, capas = leer_capas(ruta_tif)
    vis = visibilidad(capas)
    k = next((i for i, c in enumerate(capas) if c["nombre"] == HUECO), None)
    if k is None:
        raise ValueError(f"No se encuentra la capa de la foto («{HUECO}») en la carta.")
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
    afin = _color_aprobado(final, aprobada, mascara, ej_a) if aprobada else None
    if afin is not None:
        final = _afin(final, afin)

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

    if afin is not None:
        encima[:, :, :3] = _afin(encima[:, :, :3], afin)

    # la línea dorada bajo el jugador es una forma sin píxeles que Photoshop pinta por encima
    # del jugador: se saca de la imagen final, sola (lo único que va encima del jugador)
    linea_capa = np.zeros((H, W, 4), np.float32)
    linea = _linea(final, debajo, linea_capa, _colocacion(W, H)["corte"])
    la = linea_capa[:, :, 3:4]
    encima[:, :, :3] = linea_capa[:, :, :3] * la + encima[:, :, :3] * (1 - la)
    encima[:, :, 3:4] = la + encima[:, :, 3:4] * (1 - la)

    # aprender el ajuste donde el resultado no lleva nada encima
    zona = (mascara > 250) & (cubierto > 0.99) & (encima[:, :, 3] < 0.01)
    lut = ajustar_lut(antes[zona], final[zona])
    error = np.abs(aplicar_lut(antes[zona][None], lut)[0] - final[zona]).mean()
    print("error medio del ajuste de color:", round(float(error), 2), "niveles de 255")

    fuera = (ej_a < 0.002).astype(np.uint8)
    dist = cv2.distanceTransform(fuera, cv2.DIST_L2, 5)
    # el fondo que va detrás del jugador (y el que se rehace donde estaba el de ejemplo)
    # con su propio ajuste de color, aprendido en el fondo lejos del jugador: con el del
    # jugador quedaba unos niveles más oscuro y morado, y se veía el contorno del ejemplo
    zf = (mascara > 250) & (cubierto > 0.99) & (encima[:, :, 3] < 0.01) & (dist > SOMBRA_MAX + 20)
    lut_fondo = ajustar_lut(debajo[zf], final[zf])
    base = aplicar_lut(debajo, lut_fondo)
    print("error medio del fondo:", round(float(np.abs(base[zf] - final[zf]).mean()), 2), "niveles de 255")
    # carta sin jugador: el resultado final con la zona del ejemplo rehecha
    sin = final.copy()
    rehacer = (dist <= SOMBRA_MAX) & (mascara > 0)
    if linea is not None:
        # de la línea dorada para abajo el jugador no se ve (el recuadro del nombre, otra
        # forma sin píxeles, lo tapa): ahí la carta queda tal cual
        rehacer[linea:] = False
    sin[rehacer] = base[rehacer]
    ea = encima[:, :, 3:4]
    sin = np.where(rehacer[..., None], encima[:, :, :3] * ea + sin * (1 - ea), sin)

    texto = next((c for c in capas if c["nombre"] == "TEXT CLUB" and "imagen" in c), None)
    texto_alfa = None
    if texto is not None:
        l, t, r, b = texto["caja"]
        texto_alfa = np.zeros((H, W), np.float32)
        texto_alfa[t:b, l:r] = np.asarray(texto["imagen"])[:, :, 3] / 255
    quitada = _sombra_bajo_linea(sin, linea_capa, texto_alfa)
    print("sombra del ejemplo bajo la línea: oscurecía", round(quitada, 2))
    club, vacios = _club(capas, final, sin, W, H)
    return dict(W=W, H=H, fondo=sin, mascara=mascara, linea_capa=linea_capa, lut=lut, linea=linea,
                lista_encima=lista_encima, club=club, vacios=vacios)


def _guardar_imagenes(d, carpeta, mascara=True):
    os.makedirs(carpeta, exist_ok=True)
    Image.fromarray(np.clip(d["fondo"] + .5, 0, 255).astype(np.uint8)).save(os.path.join(carpeta, "fondo.png"))
    if mascara:
        Image.fromarray(d["mascara"]).save(os.path.join(carpeta, "mascara.png"))
    lc = d["linea_capa"]
    Image.fromarray(np.dstack([np.clip(lc[:, :, :3] + .5, 0, 255), lc[:, :, 3:] * 255 + .5]).astype(np.uint8),
                    "RGBA").save(os.path.join(carpeta, "encima.png"))
    np.save(os.path.join(carpeta, "lut.npy"), d["lut"])
    club = {k: dict(v) for k, v in d["club"].items()}
    for clave, (zona, im) in d["vacios"].items():
        archivo = f"sin_{clave}.png"
        Image.fromarray(np.clip(im + .5, 0, 255).astype(np.uint8)).save(os.path.join(carpeta, archivo))
        club[clave]["vacio"] = {"archivo": archivo, "x": int(zona[0]), "y": int(zona[1])}
    return club


def main(ruta_tif, carpeta=None, id_="cartas", aprobada=None, club_nombre="C.F. AMPOSTA", buscar=("amposta",)):
    """ruta_tif: el TIFF de la carta con capas y un jugador de ejemplo; carpeta: dónde
    se guarda la plantilla (por defecto, dentro del programa). Sirve para cualquier
    carta hecha con el mismo diseño (otros colores, otro club, otro año). Los colores de
    otros clubs se añaden después con variante() y se conservan al rehacer esta."""
    d = _construir(ruta_tif, aprobada)
    W, H, linea = d["W"], d["H"], d["linea"]
    carpeta = carpeta or os.path.join(DESTINO, id_)
    club = _guardar_imagenes(d, carpeta)
    anteriores = {}
    try:
        with open(os.path.join(carpeta, "plantilla.json"), encoding="utf-8") as f:
            anteriores = json.load(f).get("variantes", {})
    except (OSError, ValueError):
        pass
    _guardar(carpeta, {
        "id": id_, "nombre": "CARTAS", "tipo": "carta", "color": "CMYK", "lienzo": [W, H], "ppp": 300,
        "fondo": "fondo.png", "mascara": "mascara.png", "encima": "encima.png",
        "lut": "lut.npy", "sombra": SOMBRA, "capas_encima": d["lista_encima"],
        # desde esta fila (la línea dorada) lo de la plantilla va encima del jugador
        "linea": int(linea - 3) if linea is not None else _colocacion(W, H)["corte"] - 3,
        # nombre y escudo del club de la plantilla (para poner los de otro) y el color de
        # carta que se elige solo si el escudo elegido lleva alguna de las palabras de buscar
        "club": dict(club, texto=club_nombre, fuentes=FUENTES_CLUB),
        "buscar": list(buscar),
        # otros colores del mismo diseño (variantes/<clave>): fondo, línea, ajuste y club
        "variantes": anteriores,
        "huecos": [{"rect": [0, 0, W, H]}], "jugadores_por_hoja": 1,
        # medido en las cartas aprobadas: pelo al 14,75 % del alto de la carta
        "encuadre": {"margen": 0.1475, "alto_rel": 5.69, "centro": 0.0, "referencia": "mixto"},
        "impresion": ["tif"], "editable": "psd", "archivo": "CARTA {FOTO}",
        "un_archivo": "CARTAS {EQUIPO}", "pdf_copias": {"jugador": 1},
        "excluir": ["entrenador", "equipo"], "necesita_recorte": True,
        # sitio del jugador (la sesión CARTAS, plantilla de 3780 x 5315), a la escala de esta
        "colocacion": _colocacion(W, H),
    })


def variante(ruta_tif, clave, nombre, club_nombre, buscar, carpeta=None):
    """Añade a la plantilla de cartas otro color del mismo diseño (el TIFF de otro club):
    su fondo, su línea, su ajuste de color y el sitio de su nombre y su escudo. El jugador
    se coloca igual que en la plantilla. buscar: palabras que, en el nombre del escudo
    elegido, eligen este color solo."""
    carpeta = carpeta or os.path.join(DESTINO, "cartas")
    with open(os.path.join(carpeta, "plantilla.json"), encoding="utf-8") as f:
        p = json.load(f)
    d = _construir(ruta_tif)
    if [d["W"], d["H"]] != p["lienzo"]:
        raise ValueError("La carta no tiene el tamaño de la plantilla de cartas.")
    if d["linea"] is None or abs(d["linea"] - 3 - p["linea"]) > 4:
        raise ValueError(f"La línea dorada no está donde en la plantilla (fila {d['linea']}).")
    sub = "variantes/" + clave
    club = _guardar_imagenes(d, os.path.join(carpeta, "variantes", clave), mascara=False)
    p.setdefault("variantes", {})[clave] = {
        "nombre": nombre, "carpeta": sub, "buscar": list(buscar),
        "club": dict(club, texto=club_nombre, fuentes=FUENTES_CLUB)}
    _guardar(carpeta, p)


def _colocacion(W, H):
    from ..carta_auto import COLOCACION
    fx, fy = W / 3780, H / 5315
    c = dict(COLOCACION)
    x0, y0, x1, y1 = c["caja"]
    c["caja"] = [round(x0 * fx), round(y0 * fy), round(x1 * fx), round(y1 * fy)]
    c["pelo"], c["corte"] = round(c["pelo"] * fy), round(c["corte"] * fy)
    c["centro"], c["cabeza"] = c["centro"] * fx, round(c["cabeza"] * fy)
    return c


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--variante":
        # --variante TIF clave "Nombre del color" "NOMBRE DEL CLUB" palabra1,palabra2
        variante(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6].split(","))
    else:
        main(sys.argv[1], aprobada=sys.argv[2] if len(sys.argv) > 2 else None)

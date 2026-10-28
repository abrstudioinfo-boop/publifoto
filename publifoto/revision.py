"""Revisores automáticos: repasan cada foto y cada producto antes y después de
generar, corrigen solos lo que tienen claro y avisan solo de lo dudoso.

Funcionan en el propio ordenador (MediaPipe y OpenCV), sin internet: las fotos de
los niños no salen nunca del PC.

  silueta        compara la silueta con los puntos de la cara y corrige la medida
                 de la cabeza cuando la silueta falla (balón, brazos, pelo, fondo).
  inclinacion    endereza la cabeza en los productos de primer plano (llaveros),
                 con la regla calibrada con retocadores sobre los 14 equipos.
  clasificacion  jugador / entrenador / foto de equipo por la ropa del resto del
                 equipo, la ropa gris y el tamaño del iris (más grande en niños).
  encuadre       cada producto: cabeza y cara dentro, sin relleno de borde visible,
                 sin otra cara metida en el recorte.
  calidad        ojos cerrados, cara no encontrada.
  salida         después de generar: están todos los archivos, todas las personas,
                 tamaños y modos de color correctos.

Las reglas y umbrales salen de comparar el programa con los trabajos aprobados de
los 14 equipos de AMPOSTA y con jueces visuales (README, "Revisores").
"""
import collections
import os
from dataclasses import dataclass, replace

import numpy as np

from . import encuadre
from .marcas import medir

# --- umbrales (calibrados) ---------------------------------------------------------
PRIMER_PLANO = 3.0          # productos con alto_rel por debajo enderezan la cabeza
GIRO_K, GIRO_B = 0.30, -0.8 # giro = K * inclinación de la cara + B (grados)
GIRO_ZONA_MUERTA = 0.75
GIRO_MAX = 4.0
CUELLO_BARBILLA = -0.089    # (cuello - barbilla) / alto de la cara, mediana
CUELLO_RANGO = (-0.35, 0.12)
PELO_FRENTE = 0.553         # (frente - pelo) / alto de la cara, mediana
PELO_RANGO = (0.25, 0.95)
GRIS_ENTRENADOR = 0.08      # ningún jugador aprobado pasa de 0.072
ROPA_DISTINTA = 0.25        # distancia de la ropa a la del equipo (porteros y entrenadores)
OJOS_CERRADOS = 0.12


@dataclass
class Aviso:
    foto: str
    revisor: str
    nivel: str          # 'corregido' (lo ha arreglado solo) | 'revisar' (mirarlo) | 'error'
    texto: str
    producto: str = None


# --- silueta ------------------------------------------------------------------

def corregir_puntos(p, m):
    """Devuelve (Puntos corregidos, lista de correcciones). m: Marcas sobre la misma foto
    (ya girada si p es de una foto girada)."""
    if not m.cara:
        return p, []
    hechas = []
    alto_cara = m.barbilla[1] - m.frente[1]
    if alto_cara <= 0:
        return p, []
    q = replace(p)
    r_cuello = (p.cuello - m.barbilla[1]) / alto_cara
    if not CUELLO_RANGO[0] <= r_cuello <= CUELLO_RANGO[1]:
        q.cuello = m.barbilla[1] + CUELLO_BARBILLA * alto_cara
        hechas.append("cuello")
    r_pelo = (m.frente[1] - p.cabeza) / alto_cara
    if not PELO_RANGO[0] <= r_pelo <= PELO_RANGO[1]:
        q.cabeza = m.frente[1] - PELO_FRENTE * alto_cara
        hechas.append("pelo")
    # centro de la cabeza: la silueta puede incluir un brazo levantado o a otra persona
    cx_cara = (m.caja_cara[0] + m.caja_cara[2]) / 2
    alto_px = alto_cara * p.alto
    if abs(p.cara_x - cx_cara) * p.ancho > 0.35 * alto_px:
        q.cara_x = cx_cara
        hechas.append("centro")
    if abs(q.cuerpo_x - q.cara_x) * p.ancho > 1.2 * alto_px:
        q.cuerpo_x = q.cara_x
        hechas.append("tronco")
    return q, hechas


def marcas_de(jugador, angulo=0.0):
    m = getattr(jugador, "marcas", None)
    if m is None:
        return None
    return m.girada(angulo, jugador.puntos.ancho, jugador.puntos.alto) if angulo else m


# --- inclinación ----------------------------------------------------------------

def giro_cabeza(m, W, H):
    """Giro (grados, antihorario) que endereza la cabeza en un primer plano y si es dudoso."""
    if not m or not m.cara:
        return 0.0, False
    ojos, cara = m.angulo_ojos(W, H), m.angulo_cara(W, H)
    a = GIRO_K * (ojos + cara) / 2 + GIRO_B
    g = 0.0 if abs(a) < GIRO_ZONA_MUERTA else float(np.clip(round(a * 2) / 2, -GIRO_MAX, GIRO_MAX))
    # los dos indicadores no coinciden: la cara está de perfil o la malla ha fallado
    dudoso = abs(ojos - cara) > 4.0
    return g, dudoso


def es_primer_plano(plantilla):
    return plantilla.get("encuadre", {}).get("alto_rel", 99) < PRIMER_PLANO


# --- clasificación -----------------------------------------------------------------

def _ropa(ruta, p, m):
    """Histograma de color (4x4x4) del tronco, entre hombros y caderas."""
    from PIL import Image
    from .analisis import abrir, _ruta_cache
    sil_ruta = _ruta_cache(ruta)[:-5] + ".png"
    if not m.pose or not os.path.exists(sil_ruta):
        return None
    sil = np.asarray(Image.open(sil_ruta)) > 127
    H, W = sil.shape
    im = abrir(ruta)
    im.draft("RGB", (W * 2, H * 2))
    a = np.asarray(im.convert("RGB").resize((W, H))).astype(np.float32) / 255
    hy = np.mean([m.hombro_izq[1], m.hombro_der[1]])
    cy = np.mean([m.cadera_izq[1], m.cadera_der[1]])
    x0, x1 = sorted([m.hombro_izq[0], m.hombro_der[0]])
    zona = np.zeros_like(sil)
    zona[int((hy + 0.1 * (cy - hy)) * H):int(cy * H), int(x0 * W):int(x1 * W)] = True
    px = a[zona & sil]
    if len(px) < 50:
        return None
    h, _ = np.histogramdd(px, bins=(4, 4, 4), range=((0, 1),) * 3)
    return (h / h.sum()).ravel()


def clasificar(jugadores):
    """Pone el tipo a cada jugador no decidido a mano. Devuelve avisos."""
    avisos = []
    retratos = [j for j in jugadores if j.puntos.ancho <= j.puntos.alto]
    ropas = {j.id: _ropa(j.ruta, j.puntos, j.marcas) for j in retratos if j.marcas}
    validas = [h for h in ropas.values() if h is not None]
    mediana = np.median(validas, 0) if len(validas) >= 5 else None
    for j in jugadores:
        j._ropa_distinta = False
        if j.puntos.ancho > j.puntos.alto:
            if not getattr(j, "tipo_manual", False):
                j.tipo, j.tipo_seguro = "equipo", True
            continue
        m = j.marcas
        gris = j.puntos.gris
        h = ropas.get(j.id)
        distinta = None
        if mediana is not None and h is not None:
            distinta = float(1 - np.sum(np.sqrt(h * mediana / mediana.sum())))
        j._ropa_distinta = distinta is None or distinta >= ROPA_DISTINTA or gris >= GRIS_ENTRENADOR
        if getattr(j, "tipo_manual", False):
            j._ropa_distinta = j._ropa_distinta or j.tipo == "entrenador"
            continue
        iris = m.iris_ipd if m and m.iris_ipd else None
        if gris >= GRIS_ENTRENADOR:
            tipo, seguro = "entrenador", True
        elif distinta is not None and distinta < ROPA_DISTINTA:
            tipo, seguro = "jugador", True      # lleva la equipación del equipo
        elif iris is None:
            tipo, seguro = "jugador", False
        elif iris < 0.175:
            tipo, seguro = "entrenador", True
        elif gris >= 0.06:
            # ropa algo gris y distinta: entrenador casi siempre, pero un portero de negro
            # también puede dar este valor
            tipo, seguro = "entrenador", False
        elif gris < 0.03 and iris > 0.19:
            tipo, seguro = "jugador", True      # portero
        else:
            tipo, seguro = ("entrenador" if iris < 0.188 else "jugador"), False
        if distinta is None and tipo == "jugador" and gris >= 0.04:
            seguro = False      # sin equipo suficiente para comparar la ropa
        j.tipo, j.tipo_seguro = tipo, seguro
    # en las dudas manda el orden de las fotos: los entrenadores se hacen seguidos (al final),
    # los porteros salen sueltos entre los jugadores. Una duda que va en el mismo bloque
    # seguido de fotos "sin equipación" que un entrenador seguro es entrenador; si no, portero.
    orden = sorted(retratos, key=lambda j: j.id)
    for i, j in enumerate(orden):
        if j.tipo_seguro or getattr(j, "tipo_manual", False):
            continue
        a = b = i
        while a > 0 and orden[a - 1]._ropa_distinta:
            a -= 1
        while b < len(orden) - 1 and orden[b + 1]._ropa_distinta:
            b += 1
        con_entrenador = any(o.tipo == "entrenador" and (o.tipo_seguro or getattr(o, "tipo_manual", False))
                             for o in orden[a:b + 1] if o is not j)
        j.tipo = "entrenador" if con_entrenador else "jugador"
        avisos.append(Aviso(j.id, "clasificacion", "revisar",
                            ("Parece entrenador (va con los entrenadores)" if con_entrenador
                             else "Parece portero (va entre los jugadores)") +
                            ", pero no es seguro: compruébalo."))
    return avisos


# --- encuadre de cada producto ---------------------------------------------------

def huecos_aspecto(plantilla):
    if "calendarios" in plantilla:
        r = plantilla["calendarios"][0]["huecos"][0]["rect"]
    else:
        r = plantilla["huecos"][0]["rect"]
    return (r[2] - r[0]) / (r[3] - r[1])


def revisar_encuadre(jugador, plantilla, ajuste=None):
    """Avisos del recorte de un jugador en un producto (ya con correcciones y giro)."""
    from .productos import puntos_y_giro
    avisos = []
    p, giro = puntos_y_giro(jugador, plantilla)
    enc = encuadre.Encuadre(**plantilla["encuadre"])
    c = encuadre.calcular(p, huecos_aspecto(plantilla), enc, ajuste)
    W, H = p.ancho, p.alto
    ancho, alto = c.x1 - c.x0, c.y1 - c.y0
    v = c
    if es_circulo(plantilla):
        # imanes: solo se ve el círculo (0,806 del lado); lo de fuera queda bajo el marco
        cx, cy, r = (c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2, 0.403 * ancho
        v = encuadre.Caja(cx - r, cy - r, cx + r, cy + r)
    va, vh = v.x1 - v.x0, v.y1 - v.y0
    fuera = dict(izquierda=max(0, -v.x0) / va, derecha=max(0, v.x1 - W) / va,
                 arriba=max(0, -v.y0) / vh, abajo=max(0, v.y1 - H) / vh)
    peor = max(fuera, key=fuera.get)
    # en los imanes la franja negra de la izquierda tapa un 24% del círculo, y los aprobados
    # también se salen de la foto por ese lado (rellenado con reflejo)
    tope = 0.24 if es_circulo(plantilla) and peor == "izquierda" else 0.03
    # en las cartas el jugador va recortado (sin fondo) sobre la carta: salirse no se ve
    if fuera[peor] > tope and not plantilla.get("necesita_recorte"):
        avisos.append(Aviso(jugador.id, "encuadre", "revisar",
                            f"El recorte se sale de la foto por {peor} ({fuera[peor]:.0%}); "
                            "ese trozo se rellena con el reflejo del borde.", plantilla["id"]))
    m = marcas_de(jugador, giro)
    if m and m.cara:
        x0, y0, x1, y1 = m.caja_cara
        x0, x1, y0, y1 = x0 * W, x1 * W, y0 * H, y1 * H
        if es_circulo(plantilla):
            # imanes: la foto se ve dentro de un círculo de 0,806 del lado
            cx, cy, r = (c.x0 + c.x1) / 2, (c.y0 + c.y1) / 2, 0.403 * ancho
            puntos = [((x0 + x1) / 2, y0), ((x0 + x1) / 2, y1), (x0, (y0 + y1) / 2), (x1, (y0 + y1) / 2)]
            cortada = any(np.hypot(px - cx, py - cy) > r for px, py in puntos)
        else:
            cortada = x0 < c.x0 or x1 > c.x1 or y0 < c.y0 or y1 > c.y1
        if cortada:
            avisos.append(Aviso(jugador.id, "encuadre", "error",
                                "La cara queda cortada en el recorte.", plantilla["id"]))
    if p.cabeza * H < c.y0 - 0.01 * alto:
        avisos.append(Aviso(jugador.id, "encuadre", "error",
                            "Se corta el pelo por arriba.", plantilla["id"]))
    return avisos


def es_circulo(plantilla):
    return any("circulo" in h for h in plantilla.get("huecos", []))


# --- todo junto ------------------------------------------------------------------------

def preparar_jugador(j):
    """Marcas, corrección de la silueta y giro de la cabeza de un jugador."""
    avisos = []
    if j.puntos.ancho > j.puntos.alto:
        j.marcas = None
        return avisos
    j.marcas = medir(j.ruta)
    m = j.marcas
    if not m.cara:
        avisos.append(Aviso(j.id, "calidad", "revisar",
                            "No se ha encontrado bien la cara: revisa su encuadre."))
        j.giro_auto, j.giro_dudoso = 0.0, True
        return avisos
    q, hechas = corregir_puntos(j.puntos, m)
    if hechas:
        j.puntos = q
        avisos.append(Aviso(j.id, "silueta", "corregido",
                            "Medida de la cabeza corregida con la cara (" + ", ".join(hechas) + ")."))
    j.giro_auto, j.giro_dudoso = giro_cabeza(m, j.puntos.ancho, j.puntos.alto)
    if j.giro_dudoso:
        avisos.append(Aviso(j.id, "inclinacion", "revisar",
                            "No está claro si la cabeza está torcida (cara de perfil): mira el llavero."))
    elif j.giro_auto:
        grados = f"{j.giro_auto:+.1f}".replace(".", ",")
        avisos.append(Aviso(j.id, "inclinacion", "corregido",
                            f"Cabeza enderezada {grados}° en los primeros planos."))
    if m.caras > 1:
        avisos.append(Aviso(j.id, "calidad", "revisar",
                            f"Hay {m.caras} caras en la foto: comprueba que el recorte es de la persona correcta."))
    if m.apertura_ojos and m.apertura_ojos < OJOS_CERRADOS:
        avisos.append(Aviso(j.id, "calidad", "revisar", "Puede tener los ojos cerrados."))
    return avisos


def revisar_encuadres(trabajo):
    from . import productos
    from .motor import jugadores_para
    avisos = []
    for id_ in trabajo.productos:
        pl = productos.cargar_plantilla(id_)
        aj = trabajo.ajustes.get(id_, {})
        for j in jugadores_para(trabajo, pl):
            if j.puntos.ancho > j.puntos.alto:
                continue
            avisos += revisar_encuadre(j, pl, aj.get(j.id))
    return avisos + revisar_presencia(trabajo)


def _visible(rect, encima):
    """Parte de rect (0..1) que no queda tapada por los rectángulos de encima."""
    x0, y0, x1, y1 = rect
    xs, ys = np.meshgrid(np.linspace(x0, x1, 41)[:-1] + (x1 - x0) / 80,
                         np.linspace(y0, y1, 41)[:-1] + (y1 - y0) / 80)
    tapado = np.zeros(xs.shape, bool)
    for a in encima:
        tapado |= (xs > a[0]) & (xs < a[2]) & (ys > a[1]) & (ys < a[3])
    return 1.0 - tapado.mean()


def _zona(plantilla, rect, foto=None):
    """Lo que tiene que verse de una foto: el círculo en los imanes (el resto del
    cuadrado es sangrado y queda debajo del vecino a propósito), la foto entera en lo
    demás. Con foto (rectángulo real en el PDF) se lleva a donde está esa foto."""
    h = next((h for h in plantilla.get("huecos", []) if h["rect"] == rect), {})
    z = h.get("circulo", rect)
    if foto is None:
        return z
    ex, ey = (foto[2] - foto[0]) / (rect[2] - rect[0]), (foto[3] - foto[1]) / (rect[3] - rect[1])
    return [foto[0] + (z[0] - rect[0]) * ex, foto[1] + (z[1] - rect[1]) * ey,
            foto[0] + (z[2] - rect[0]) * ex, foto[1] + (z[3] - rect[1]) * ey]


def revisar_presencia(trabajo, salidas=None):
    """Que cada persona que se va a imprimir salga, entera y una vez, en cada producto.
    Sin salidas mira el reparto en las hojas (antes de generar); con salidas mira
    también lo que hay de verdad en los PDF y en los archivos por capas."""
    from . import productos
    from .motor import jugadores_para
    avisos = []
    for id_ in trabajo.productos:
        pl = productos.cargar_plantilla(id_)
        jug = jugadores_para(trabajo, pl)
        if not jug:
            continue
        hojas = productos.hojas(pl, jug)
        sitios = [productos.colocacion(pl, h) for h in hojas]
        puestos = collections.Counter()
        for n, (hoja, sitio) in enumerate(zip(hojas, sitios), 1):
            donde = f" (hoja {n})" if len(hojas) > 1 else ""
            for j in hoja:
                mios = [k for k, s in enumerate(sitio) if s[2] is j]
                if not mios:
                    avisos.append(Aviso(j.id, "presencia", "error",
                                        f"No tiene hueco en la hoja{donde}: no saldría.", id_))
                    continue
                puestos[j.id] += 1
                # lo que se pinta después queda encima
                vis = max(_visible(_zona(pl, sitio[k][0]), [s[0] for s in sitio[k + 1:] if s[2] is not j])
                          for k in mios)
                if vis < 0.9:
                    avisos.append(Aviso(j.id, "presencia", "error",
                                        f"Queda tapado por otra foto{donde}: solo se ve un {vis:.0%}.", id_))
        for j in jug:
            if puestos[j.id] == 0 and not any(a.foto == j.id and a.producto == id_ for a in avisos):
                avisos.append(Aviso(j.id, "presencia", "error", "No sale en ninguna hoja.", id_))
            elif puestos[j.id] > 1:
                avisos.append(Aviso(j.id, "presencia", "error", f"Sale {puestos[j.id]} veces.", id_))
        if salidas:
            avisos += _presencia_en_archivos(trabajo, pl, hojas, sitios, salidas)
    return avisos


def _fotos_jugadores(pg):
    """Rectángulos de las fotos puestas directamente en la página, en el orden en que
    se pintan. Las imágenes del diseño van dentro de la página de fondo y no cuentan."""
    propias = {i[0] for i in pg.get_images(full=True) if not i[-1]}
    return [tuple(i["bbox"]) for i in pg.get_image_info(xrefs=True) if i["xref"] in propias]


def _presencia_en_archivos(trabajo, pl, hojas, sitios, salidas):
    """Comprueba lo generado sin fiarse del reparto: fotos de verdad en cada página del
    PDF, y una capa por persona en los archivos por capas de las hojas."""
    from . import productos
    avisos = []
    base = os.path.join(trabajo.carpeta_equipo, pl["nombre"])
    if pl["tipo"] == "pdf":
        import pymupdf as fitz
        for ruta in salidas:
            if not (ruta.lower().endswith(".pdf") and os.path.dirname(ruta) == os.path.join(base, "IMPRESION")):
                continue
            with fitz.open(ruta) as d:
                for n, (pg, hoja, sitio) in enumerate(zip(d, hojas, sitios), 1):
                    # solo las fotos de los jugadores (el diseño va como página aparte)
                    fotos = _fotos_jugadores(pg)
                    if len(fotos) != len(sitio):
                        avisos.append(Aviso(os.path.basename(ruta), "salida", "error",
                                            f"La hoja {n} tiene {len(fotos)} fotos y debería tener {len(sitio)}.", pl["id"]))
                        continue
                    # cada persona debe verse: ninguna foto de otro la tapa
                    for k, (f, (rect, _, j)) in enumerate(zip(fotos, sitio)):
                        encima = [g for g, s in zip(fotos[k + 1:], sitio[k + 1:]) if s[2] is not j]
                        if _visible(_zona(pl, rect, f), encima) < 0.9:
                            avisos.append(Aviso(j.id, "salida", "error",
                                                f"En el PDF queda tapado por otra foto (hoja {n}).", pl["id"]))
    elif not (pl.get("jugadores_por_hoja", 1) == 1 and len(pl.get("huecos", [])) == 1):
        from psd_tools import PSDImage
        for n, hoja in enumerate(hojas, 1):
            ruta = os.path.join(base, "EDITABLE", productos.nombre_archivo(pl, trabajo.equipo, n=n) + ".psd")
            if ruta not in salidas:
                continue
            try:
                capas = {c.name for c in PSDImage.open(ruta)}
            except Exception as e:
                avisos.append(Aviso(os.path.basename(ruta), "salida", "error", f"No se puede abrir: {e}", pl["id"]))
                continue
            for j in hoja:
                if j.nombre not in capas:
                    avisos.append(Aviso(j.id, "salida", "error", f"No está en la hoja {n}.", pl["id"]))
    return avisos


def revisar_salida(trabajo, salidas):
    """Comprueba los archivos generados. Devuelve avisos de nivel 'error'."""
    from PIL import Image
    from . import productos
    from .motor import jugadores_para
    avisos = []
    for ruta in salidas:
        if not os.path.exists(ruta) or os.path.getsize(ruta) == 0:
            avisos.append(Aviso(os.path.basename(ruta), "salida", "error", "Archivo no creado o vacío."))
    for id_ in trabajo.productos:
        pl = productos.cargar_plantilla(id_)
        imp = os.path.join(trabajo.carpeta_equipo, pl["nombre"], "IMPRESION")
        jug = jugadores_para(trabajo, pl)
        if not jug:
            continue
        hechos = [s for s in salidas if os.path.dirname(s) == imp]
        if not hechos:
            avisos.append(Aviso("", "salida", "error", "No se ha generado nada para imprimir.", id_))
            continue
        if pl.get("jugadores_por_hoja", 1) == 1 and len(pl.get("huecos", [])) == 1:
            nombres = {os.path.splitext(os.path.basename(s))[0] for s in hechos}
            for j in jug:
                if productos.nombre_archivo(pl, trabajo.equipo, foto=j.nombre) not in nombres:
                    avisos.append(Aviso(j.id, "salida", "error", "Falta su archivo de impresión.", id_))
        for s in hechos:
            if s.lower().endswith((".jpg", ".tif")):
                with Image.open(s) as im:
                    if pl.get("lienzo") and list(im.size) != list(pl["lienzo"]):
                        avisos.append(Aviso(os.path.basename(s), "salida", "error",
                                            f"Tamaño {im.size} distinto de la plantilla {tuple(pl['lienzo'])}.", id_))
                    if s.lower().endswith(".tif") and pl["color"] == "CMYK" and im.mode != "CMYK":
                        avisos.append(Aviso(os.path.basename(s), "salida", "error", "No está en CMYK.", id_))
            if s.lower().endswith(".pdf"):
                import pymupdf as fitz
                with fitz.open(s) as d:
                    n = len(productos.hojas(pl, jug))
                    if len(d) != n:
                        avisos.append(Aviso(os.path.basename(s), "salida", "error",
                                            f"Tiene {len(d)} páginas y debería tener {n}.", id_))
    return avisos + revisar_presencia(trabajo, salidas)

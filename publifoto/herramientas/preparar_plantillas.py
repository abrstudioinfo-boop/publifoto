"""Convierte las plantillas originales de Adobe (.ai, .pdf, .tif con capas) en
plantillas abiertas que el programa usa sin Adobe.

Solo lo ejecuta quien mantiene el programa, una vez por plantilla:
    python -m publifoto.herramientas.preparar_plantillas "<carpeta con los originales>"
"""
import json
import os
import re
import sys

import numpy as np
import pymupdf as fitz
from PIL import Image

from .tiff_capas import leer_capas

Image.MAX_IMAGE_PIXELS = None
DESTINO = os.path.join(os.path.dirname(os.path.dirname(__file__)), "plantillas")


def _guardar(id_, cfg):
    os.makedirs(os.path.join(DESTINO, id_), exist_ok=True)
    with open(os.path.join(DESTINO, id_, "plantilla.json"), "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print("plantilla lista:", id_)


def _pdf_sin_fotos(origen, pagina, filtro_foto, texto_quitar=None):
    """Copia una página quitando las fotos (y opcionalmente un texto) sin tocar
    el resto del diseño vectorial."""
    src = fitz.open(origen)
    d = fitz.open()
    d.insert_pdf(src, from_page=pagina, to_page=pagina)
    pg = d[0]
    fotos = [i for i in pg.get_image_info(xrefs=True) if filtro_foto(i)]
    # quitar solo las órdenes que dibujan las fotos de ejemplo de la propia página
    # (las imágenes dentro de otros objetos, como el escudo de marca de agua, se quedan)
    xrefs = {i["xref"] for i in fotos}
    por_stream = {}
    for img in pg.get_images(full=True):
        if img[0] in xrefs:
            # img[9]: objeto que la dibuja (0 = la página; si no, un formulario)
            streams = pg.get_contents() if img[9] == 0 else [img[9]]
            for s in streams:
                por_stream.setdefault(s, set()).add(img[7])
    for stream, nombres in por_stream.items():
        contenido = d.xref_stream(stream).decode("latin1")
        for n in nombres:
            contenido = re.sub(rf"/{re.escape(n)}\s+Do\b", "", contenido)
        d.update_stream(stream, contenido.encode("latin1"))
        # quitar también la referencia, para que la foto de ejemplo (un niño real)
        # no quede escondida dentro del PDF
        duenyo = pg.xref if stream in pg.get_contents() else stream
        for n in nombres:
            d.xref_set_key(duenyo, f"Resources/XObject/{n}", "null")
    texto = None
    if texto_quitar:
        for b in pg.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    if s["text"].strip() == texto_quitar:
                        texto = s
                        pg.add_redact_annot(fitz.Rect(s["bbox"]), fill=False)
        pg.apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE,
                            graphics=fitz.PDF_REDACT_LINE_ART_NONE,
                            text=fitz.PDF_REDACT_TEXT_REMOVE)
    return d, fotos, texto


def _icc_fogra39(d):
    """Asigna el perfil Coated FOGRA39 a las imágenes CMYK que no lo llevan."""
    from ..color import icc_fogra
    icc = d.get_new_xref()
    d.update_object(icc, "<< /N 4 /Alternate /DeviceCMYK >>")
    d.update_stream(icc, icc_fogra())
    for x in range(1, d.xref_length()):
        if d.xref_get_key(x, "Subtype")[1] == "/Image" and d.xref_get_key(x, "ColorSpace")[1] == "/DeviceCMYK":
            d.xref_set_key(x, "ColorSpace", f"[/ICCBased {icc} 0 R]")


def _bloques(contenido):
    """Divide un flujo de contenido en bloques de primer nivel q ... Q y BT ... ET."""
    bloques, nivel, texto, actual = [], 0, False, []
    for tok in re.findall(r"\S+|\s+", contenido):
        actual.append(tok)
        if tok == "q":
            nivel += 1
        elif tok == "Q":
            nivel -= 1
        elif tok == "BT":
            texto = True
        elif tok == "ET":
            texto = False
        # fin de bloque: Q, ET o una orden de pintado de trazado (textos en contornos)
        if nivel == 0 and not texto and tok in ("Q", "ET", "f", "F", "f*", "S", "s", "B", "B*", "b", "b*", "n"):
            bloques.append("".join(actual))
            actual = []
    if "".join(actual).strip():
        bloques.append("".join(actual))
    return bloques


def _extension_x(d, stream, contenido, ppp=30):
    """Extensión horizontal (pt) de lo que se ve al dibujar solo 'contenido' en ese flujo."""
    original = d.xref_stream(stream)
    d.update_stream(stream, contenido.encode("latin1"))
    pix = d[0].get_pixmap(dpi=ppp, colorspace=fitz.csGRAY)
    d.update_stream(stream, original)
    a = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width)
    xs = np.nonzero((a < 250).any(0))[0]
    if not len(xs):
        return None
    return xs.min() * 72 / ppp, (xs.max() + 1) * 72 / ppp


def media_hoja(origen, destino, x_corte):
    """Copia el fondo dejando solo lo que queda a la izquierda de x_corte (pt).
    Se quita del archivo (no solo se tapa) lo que está entero a la derecha."""
    d = fitz.open(origen)
    pg = d[0]
    # formularios de primer nivel y, dentro de cada uno, sus bloques o subformularios
    pagina = pg.get_contents()[0]
    usados = re.findall(r"/(\w+)\s+Do", d.xref_stream(pagina).decode("latin1"))
    recursos = d.xref_get_key(pg.xref, "Resources")[1]
    formas = dict(re.findall(r"/(\w+) (\d+) 0 R", recursos.split("/XObject")[1])) if "/XObject" in recursos else {}
    for nombre in usados:
        xref = int(formas[nombre])
        flujo = d.xref_stream(xref).decode("latin1")
        partes = _bloques(flujo)
        quedan = []
        for b in partes:
            ext = _extension_x_en(d, pagina, nombre, xref, b)
            if ext is None:
                # no se ve: se queda solo si su trazado está en la mitad izquierda
                ext = _caja_trazado(b)
            if ext is None or ext[0] < x_corte:
                quedan.append(b)
        d.update_stream(xref, "".join(quedan).encode("latin1"))
    d.save(destino, garbage=4, deflate=True)
    # comprobación: la parte que se queda debe verse idéntica al fondo completo
    a = fitz.open(origen)[0].get_pixmap(dpi=60, colorspace=fitz.csRGB)
    b = fitz.open(destino)[0].get_pixmap(dpi=60, colorspace=fitz.csRGB)
    A = np.frombuffer(a.samples, np.uint8).reshape(a.height, a.width, 3).astype(int)
    B = np.frombuffer(b.samples, np.uint8).reshape(b.height, b.width, 3).astype(int)
    c = int(x_corte / 72 * 60)
    dif_izq = np.abs(A[:, :c - 2] - B[:, :c - 2]).max()
    resto_der = (B[:, c + 2:] < 245).any(2).sum()
    if dif_izq > 8 or resto_der:
        raise ValueError(f"media hoja incorrecta: diferencia izquierda {dif_izq}, píxeles a la derecha {resto_der}")


def _caja_trazado(bloque):
    """Extensión x aproximada de un bloque invisible, por las coordenadas de sus
    rectángulos y trazos (sin transformaciones 'cm'; si las hay, no se decide)."""
    if " cm" in bloque:
        return None
    xs = [float(m) for m in re.findall(r"(-?\d+\.?\d*)\s+-?\d+\.?\d*\s+(?:-?\d+\.?\d*\s+-?\d+\.?\d*\s+re|m|l)\b", bloque)]
    return (min(xs), max(xs)) if xs else None


def _extension_x_en(d, pagina, nombre, xref, bloque):
    """Extensión de un bloque de un formulario, dibujando solo ese formulario."""
    original_pag = d.xref_stream(pagina)
    d.update_stream(pagina, f"q /{nombre} Do Q".encode("latin1"))
    try:
        return _extension_x(d, xref, bloque)
    finally:
        d.update_stream(pagina, original_pag)


def _dentro(a, b):
    """Parte del rectángulo a que queda dentro de b (0..1)."""
    ancho, alto = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    return ancho * alto / ((a[2] - a[0]) * (a[3] - a[1])) if ancho > 0 and alto > 0 else 0.0


def imanes(carpeta):
    id_ = "imanes"
    d, fotos, texto = _pdf_sin_fotos(os.path.join(carpeta, "IMANS FUTBOL.ai"), 0,
                                     lambda i: i["width"] > 1000, texto_quitar="S10 A")
    pg = d[0]
    clips = []
    for dr in pg.get_drawings(extended=True):
        if dr["type"] == "clip" and 150 < dr["scissor"].width < 400:
            r = tuple(round(v, 2) for v in dr["scissor"])
            # el .ai repite algunos círculos (y trozos de círculo) encima de otros:
            # cada uno se llevaría un jugador y el de encima taparía al de debajo
            if not any(_dentro(r, c) > 0.5 or _dentro(c, r) > 0.5 for c in clips):
                clips.append(r)
    # la foto va en un cuadrado mayor que el círculo (sangrado para el troquel):
    # en los imanes aprobados el círculo ocupa del 9,7 % al 90,3 % del cuadrado
    huecos = []
    for c in sorted(clips, key=lambda c: (round(c[1] / 50), c[0])):
        lado = (c[2] - c[0]) / 0.806
        m = (lado - (c[2] - c[0])) / 2
        huecos.append({"rect": [round(c[0] - m, 2), round(c[1] - m, 2), round(c[2] + m, 2), round(c[3] + m, 2)],
                       "circulo": list(c)})
    os.makedirs(os.path.join(DESTINO, id_), exist_ok=True)
    d.save(os.path.join(DESTINO, id_, "fondo.pdf"), garbage=4, deflate=True)
    # el nombre del equipo va centrado donde estaba el de ejemplo
    x0, y0, x1, y1 = texto["bbox"]
    _guardar(id_, {
        "id": id_, "nombre": "IMANES", "tipo": "pdf", "color": "RGB", "fondo": "fondo.pdf",
        "huecos": huecos, "jugadores_por_hoja": len(huecos), "ppp_fotos": 400,
        "encuadre": {"margen": 0.216, "alto_rel": 5.36, "centro": -0.033, "referencia": "mixto"},
        "textos": [{"texto": "{EQUIPO}", "centro_x": round((x0 + x1) / 2, 2) + 3.7, "base_y": round(texto["origin"][1], 2),
                    "tam": texto["size"], "fuente": "SourceSans3-Regular.ttf", "color": [0, 0, 0]}],
        "impresion": ["pdf", "jpg"], "editable": "pdf", "archivo": "IMANES {EQUIPO}",
        "excluir": ["entrenador", "equipo"],
    })


def sobremesa(carpeta):
    id_ = "sobremesa"
    origen = os.path.join(carpeta, "CALENDARI SOBRETAULA 2027.pdf")
    d, fotos, _ = _pdf_sin_fotos(origen, 0, lambda i: i["width"] > 850 and i["height"] > 1000)
    # marcos rojos (trazo de 0,77 mm del propio marco, ya incluido en el fondo)
    marcos = []
    for dr in d[0].get_drawings():
        r = dr["rect"]
        if r.width > 150 and r.height > 200 and dr.get("color") and dr["type"] == "s":
            marcos.append({"rect": [round(v, 2) for v in r], "grosor": dr["width"]})
    # la foto ocupa exactamente el marco rojo y nunca se sale de él (ni recortada:
    # algunos visores y RIP muestran la imagen entera). Cada calendario lleva al
    # mismo jugador abajo (delantera) y arriba reflejado (trasera, girada 180°).
    W = d[0].rect.width
    calendarios = []
    for lado in (0, 1):
        ms = [m for m in marcos if (m["rect"][0] >= W / 2) == bool(lado)]
        baix = max(ms, key=lambda m: m["rect"][1])
        dalt = min(ms, key=lambda m: m["rect"][1])
        calendarios.append({
            "zona": [round(lado * W / 2, 2), 0, round((lado + 1) * W / 2, 2), round(d[0].rect.height, 2)],
            "huecos": [{"rect": baix["rect"], "espejo_vertical": False, "nombre": "BAIX"},
                       {"rect": dalt["rect"], "espejo_vertical": True, "nombre": "DALT"}]})
    os.makedirs(os.path.join(DESTINO, id_), exist_ok=True)
    _icc_fogra39(d)
    fondo = os.path.join(DESTINO, id_, "fondo.pdf")
    d.save(fondo, garbage=4, deflate=True)
    # hoja con un solo jugador: fondo solo con el calendario izquierdo (y las marcas
    # de corte centrales, que están en x = 226 mm)
    media_hoja(fondo, os.path.join(DESTINO, id_, "fondo_izquierda.pdf"), W / 2 + 2 * 72 / 25.4)
    _guardar(id_, {
        "id": id_, "nombre": "CALENDARIOS SOBREMESA", "tipo": "pdf", "color": "CMYK", "fondo": "fondo.pdf",
        "calendarios": calendarios, "marcos": marcos, "ppp_fotos": 300,
        "fondos_parciales": {"1": "fondo_izquierda.pdf"},
        # reglas aprobadas (REGLAS.txt de la sesión CALENDARIOS SOBRE MESA) y medido en S9 A:
        # pelo al 10 % del marco, bajo de la camiseta un 4 % por debajo, centrado entre cara y cuerpo
        "encuadre": {"margen": 0.10, "alto_rel": 3.73, "centro": 0.0, "referencia": "mixto"},
        "impresion": ["pdf"], "editable": "pdf", "archivo": "CALENDARI SOBRETAULA 2027 - {EQUIPO}",
        "excluir": ["entrenador", "equipo"], "guardar_recortes": True,
    })


def _capa_png(capa, ruta):
    if "cmyk" in capa:
        capa["cmyk"].save(ruta + ".tif", compression="tiff_lzw")
        capa["alfa"].save(ruta + "_alfa.png")
        return os.path.basename(ruta) + ".tif"
    capa["imagen"].save(ruta + ".png")
    return os.path.basename(ruta) + ".png"


def foto_con_logo(carpeta, id_, archivo, nombre, color, encuadre, impresion, editable, nombre_archivo, excluir):
    (W, H), modo, capas = leer_capas(os.path.join(carpeta, archivo), solo=lambda n: "AMPOSTA" in n.upper())
    os.makedirs(os.path.join(DESTINO, id_), exist_ok=True)
    capas_encima = []
    for c in capas:
        if c["visible"] and ("imagen" in c or "cmyk" in c) and "AMPOSTA" in c["nombre"].upper():
            l, t, r, b = c["caja"]
            f = _capa_png(c, os.path.join(DESTINO, id_, "logo"))
            capas_encima.append({"nombre": c["nombre"], "archivo": f, "x": l, "y": t})
    _guardar(id_, {
        "id": id_, "nombre": nombre, "tipo": "raster", "color": color, "lienzo": [W, H], "ppp": 300,
        "fondo_color": [255, 255, 255],
        "huecos": [{"rect": [0, 0, W, H]}], "jugadores_por_hoja": 1,
        "encuadre": encuadre, "encima": capas_encima,
        "impresion": impresion, "editable": editable, "archivo": nombre_archivo,
        "excluir": excluir,
    })


def llaveros():
    id_ = "llaveros"
    W, H = 2362, 1795
    huecos = []
    for fila_y in (50, 1110):
        for i in range(5):
            x0 = round(27 + i * 460.6)
            huecos.append({"rect": [x0, fila_y, round(27 + (i + 1) * 460.6), fila_y + 650], "jugador": i})
    _guardar(id_, {
        "id": id_, "nombre": "LLAVEROS", "tipo": "raster", "color": "RGB", "lienzo": [W, H], "ppp": 300,
        "fondo_color": [194, 194, 194], "huecos": huecos, "jugadores_por_hoja": 5,
        "encuadre": {"margen": 0.0855, "alto_rel": 2.22, "centro": -0.004, "referencia": "cara"},
        "encima": [], "impresion": ["jpg"], "editable": "psd", "archivo": "LLAVEROS {EQUIPO} {N}",
        "excluir": ["entrenador", "equipo"],
    })


def main(carpeta):
    imanes(carpeta)
    sobremesa(carpeta)
    foto_con_logo(carpeta, "pared", "CAL PARET.tif", "CALENDARIOS PARED", "CMYK",
                  {"margen": 0.083, "alto_rel": 4.165, "centro": 0.014, "referencia": "mixto"},
                  ["tif"], "psd", "CALENDARIO PARED {EQUIPO} - {FOTO}", ["equipo"])
    foto_con_logo(carpeta, "15x20", os.path.join("15 x 20", "S11 A", "15 X 20.tif"), "15 X 20 CON LOGO", "RGB",
                  {"margen": 0.083, "alto_rel": 4.03, "centro": 0.016, "referencia": "mixto"},
                  ["jpg"], "psd", "{FOTO}", ["entrenador", "equipo"])
    llaveros()


if __name__ == "__main__":
    main(sys.argv[1])

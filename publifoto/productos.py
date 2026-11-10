"""Generación de cada producto a partir de su plantilla abierta.

Todas las funciones reciben la plantilla (dict de plantilla.json), la lista de
jugadores de la hoja y el nombre del equipo, y escriben los archivos de
IMPRESION y EDITABLE.
"""
import io
import json
import os

import numpy as np
import pymupdf as fitz
from PIL import Image

from . import color, encuadre, retoque
from .analisis import abrir, girada, girar

PLANTILLAS = os.path.join(os.path.dirname(__file__), "plantillas")
# las letras van dentro del programa (libres, OFL) para que salga igual en Windows y Mac
FUENTES = os.path.join(os.path.dirname(__file__), "recursos", "fuentes")
_FUENTES_SISTEMA = [os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"),
                    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Fonts"),
                    "/Library/Fonts", "/System/Library/Fonts", os.path.expanduser("~/Library/Fonts")]


def ruta_fuente(nombre):
    for carpeta in [FUENTES] + _FUENTES_SISTEMA:
        ruta = os.path.join(carpeta, nombre)
        if os.path.exists(ruta):
            return ruta
    raise FileNotFoundError(f"No se encuentra la letra {nombre}")


def carpeta_plantillas_usuario():
    """Plantillas actualizadas desde el programa (botón «Actualizar plantilla…»):
    tienen preferencia sobre las que vienen dentro del programa."""
    from .club import carpeta_datos
    return os.path.join(carpeta_datos(), "plantillas")


def carpeta_plantilla(id_):
    propia = os.path.join(carpeta_plantillas_usuario(), id_)
    if os.path.exists(os.path.join(propia, "plantilla.json")):
        return propia
    return os.path.join(PLANTILLAS, id_)


def cargar_plantilla(id_):
    carpeta = carpeta_plantilla(id_)
    with open(os.path.join(carpeta, "plantilla.json"), encoding="utf-8") as f:
        p = json.load(f)
    p["_carpeta"] = carpeta
    _limpiar_huecos(p)
    return p


def _solape(a, b):
    """Parte del rectángulo a que queda debajo de b (0..1)."""
    ancho = min(a[2], b[2]) - max(a[0], b[0])
    alto = min(a[3], b[3]) - max(a[1], b[1])
    if ancho <= 0 or alto <= 0:
        return 0.0
    return ancho * alto / ((a[2] - a[0]) * (a[3] - a[1]))


def _limpiar_huecos(p):
    """Al sacar los marcos de la plantilla original salen a veces marcos repetidos o
    trozos de marco encima de otro. Cada uno se llevaría un jugador distinto y el de
    encima taparía al de debajo, que desaparecería de la hoja. Se quitan aquí y se
    ajusta cuántos jugadores caben por hoja."""
    huecos = p.get("huecos")
    if not huecos or len(huecos) < 2:
        return
    buenos = []
    for i, h in enumerate(huecos):
        idx = h.get("jugador", i)
        if any(g.get("jugador", k) != idx and
               max(_solape(h["rect"], g["rect"]), _solape(g["rect"], h["rect"])) > 0.5
               for k, g in buenos):
            continue
        buenos.append((i, h))
    if len(buenos) == len(huecos):
        return
    # numeración seguida: el jugador n de la hoja va al hueco n
    con_indice = any("jugador" in h for h in huecos)
    p["huecos"] = [h for _, h in buenos] if con_indice else \
        [{k: v for k, v in h.items() if k != "jugador"} for _, h in buenos]
    plazas = len({h.get("jugador", i) for i, h in enumerate(p["huecos"])})
    if p.get("jugadores_por_hoja"):
        p["jugadores_por_hoja"] = min(p["jugadores_por_hoja"], plazas)


def colocacion(plantilla, jugadores):
    """Dónde va cada jugador de una hoja, en el orden en que se pinta:
    [(rect, espejo, jugador)]. Es lo que usan raster() y pdf(), y lo que mira el
    revisor de presencia."""
    if "calendarios" in plantilla:
        return [(h["rect"], h.get("espejo_vertical", False), j)
                for cal, j in zip(plantilla["calendarios"], jugadores) for h in cal["huecos"]]
    sitio = []
    for i, h in enumerate(plantilla["huecos"]):
        idx = h.get("jugador", i)
        if idx < len(jugadores):
            sitio.append((h["rect"], False, jugadores[idx]))
    return sitio


def lista_plantillas():
    return [cargar_plantilla(d) for d in sorted(os.listdir(PLANTILLAS))
            if os.path.exists(os.path.join(PLANTILLAS, d, "plantilla.json"))]


def textos_marca(marca):
    """Valores de {CLUB} y {TEMPORADA} en los textos de las plantillas."""
    from .club import temporada_actual
    marca = marca or {}
    return {"CLUB": marca.get("club") or "C.F. AMPOSTA",
            "TEMPORADA": marca.get("temporada") or temporada_actual()}


def nombre_archivo(plantilla, equipo, n=1, foto=""):
    return plantilla["archivo"].format(EQUIPO=equipo, N=n, FOTO=foto).strip()


def hojas(plantilla, jugadores):
    """Reparte los jugadores en hojas según la plantilla."""
    n = plantilla.get("jugadores_por_hoja") or len(plantilla.get("calendarios", [])) or 1
    return [jugadores[i:i + n] for i in range(0, len(jugadores), n)]


# --- recorte de cada jugador -------------------------------------------------

def giro_total(jugador, plantilla=None):
    """Giro manual (todos los productos) + giro automático de la cabeza (solo en los
    primeros planos, como los llaveros), en grados antihorario."""
    from .revision import es_primer_plano
    giro = getattr(jugador, "giro", 0.0) or 0.0
    if plantilla is not None and es_primer_plano(plantilla) and not getattr(jugador, "sin_giro_auto", False):
        giro += getattr(jugador, "giro_auto", 0.0) or 0.0
    return round(giro, 2)


def puntos_y_giro(jugador, plantilla=None):
    """Puntos del jugador ya enderezado con su giro (o los originales si no se gira).
    Las correcciones de la silueta con la cara se vuelven a aplicar sobre la foto girada."""
    from .revision import corregir_puntos, marcas_de
    giro = giro_total(jugador, plantilla)
    if not giro:
        return jugador.puntos, giro
    p = girada(jugador.ruta, jugador.puntos, giro)
    m = marcas_de(jugador, giro)
    if m is not None:
        p, _ = corregir_puntos(p, m)
    return p, giro


def foto_recortada(jugador, plantilla, tam, ajuste=None, recorte=False):
    """Recorta la foto del jugador al tamaño del hueco (px) con el encuadre de la plantilla.
    Si el jugador lleva giro, la foto se endereza primero y el encuadre se calcula
    sobre la foto enderezada: mismas medidas que el resto de jugadores."""
    enc = encuadre.Encuadre(**plantilla["encuadre"])
    puntos, giro = puntos_y_giro(jugador, plantilla)
    caja = encuadre.calcular(puntos, tam[0] / tam[1], enc, ajuste)
    ruta = jugador.ruta_recorte if recorte else jugador.ruta
    im = abrir(ruta)
    perfil = None
    if recorte:
        im = im.convert("RGBA")
    else:
        # el perfil de color se aplica al final, solo al trozo recortado (mucho más rápido
        # que convertir la foto entera)
        if im.mode == "CMYK":
            im = color.a_rgb(im)
        else:
            perfil = color.perfil_origen(im)
            im = im if im.mode == "RGB" else im.convert("RGB")
    if recorte and im.size != (jugador.puntos.ancho, jugador.puntos.alto):
        # el recorte debe tener el mismo tamaño que la foto arreglada
        im = im.resize((jugador.puntos.ancho, jugador.puntos.alto), Image.LANCZOS)
    im = retoque.de_jugador(jugador, im)
    trozo = encuadre.recortar(girar(im, giro), caja, tam)
    return color.a_rgb(trozo, perfil) if perfil is not None else trozo


# --- productos raster (llaveros, 15x20, pared) -------------------------------

_encimas = {}
_en_cmyk = {}


def limpiar_cache():
    """Al empezar a generar: las plantillas o el escudo pueden haber cambiado."""
    _encimas.clear()
    _en_cmyk.clear()
    _comprimidas.clear()
    _fondos.clear()


def cmyk_de_capa(im):
    """Una capa RGB(A) de la plantilla en CMYK, convertida una sola vez."""
    clave = id(im)
    if clave not in _en_cmyk:
        _en_cmyk[clave] = (im, color.a_cmyk(im.convert("RGB")))
    return _en_cmyk[clave][1]


def _encima(plantilla, marca=None):
    """Capas que van encima de las fotos (logo, textos). Se leen una vez por plantilla."""
    clave = (plantilla["_carpeta"], (marca or {}).get("escudo"))
    if clave not in _encimas:
        _encimas[clave] = _leer_encima(plantilla, marca)
    return list(_encimas[clave])


def _leer_encima(plantilla, marca=None):
    capas = []
    escudo = (marca or {}).get("escudo")
    for c in plantilla.get("encima", []):
        ruta = os.path.join(plantilla["_carpeta"], c["archivo"])
        im = Image.open(ruta)
        im.load()
        alfa = None
        if im.mode == "CMYK":
            alfa = Image.open(ruta.replace(".tif", "_alfa.png")).convert("L")
        if c.get("escudo") and escudo:
            # el escudo del club, centrado en el sitio y con el tamaño del de la plantilla
            from .club import ajustado
            nombre = os.path.splitext(os.path.basename(escudo))[0]
            capas.append((nombre, ajustado(escudo, im.size), None, c["x"], c["y"]))
            continue
        capas.append((c["nombre"], im, alfa, c["x"], c["y"]))
    return capas


_fondos = {}


def _fondo_liso(tam, rgb, cmyk):
    """Lienzo de un color (en CMYK si toca). Se convierte un solo píxel: es igual en todo."""
    clave = (tam, rgb, cmyk)
    if clave not in _fondos:
        if cmyk:
            px = color.a_cmyk(Image.new("RGB", (1, 1), rgb)).getpixel((0, 0))
            _fondos[clave] = Image.new("CMYK", tam, px)
        else:
            _fondos[clave] = Image.new("RGB", tam, rgb)
    return _fondos[clave].copy()


def raster(plantilla, jugadores, equipo, ajustes, n_hoja=1, marca=None):
    """Devuelve (imagen_final, capas) para una hoja. capas = [(nombre, im, alfa, x, y)]."""
    W, H = plantilla["lienzo"]
    cmyk = plantilla["color"] == "CMYK"
    fondo = _fondo_liso((W, H), tuple(plantilla.get("fondo_color", [255, 255, 255])), cmyk)
    capas = [("Fondo", fondo, None, 0, 0)]
    for rect, _, j in colocacion(plantilla, jugadores):
        x0, y0, x1, y1 = [int(round(v)) for v in rect]
        x0c, y0c = max(0, x0), max(0, y0)
        x1c, y1c = min(W, x1), min(H, y1)
        foto = foto_recortada(j, plantilla, (x1 - x0, y1 - y0), ajustes.get(j.id))
        foto = foto.crop((x0c - x0, y0c - y0, x1c - x0, y1c - y0))
        if cmyk:
            foto = color.a_cmyk(foto)
        capas.append((j.nombre, foto, None, x0c, y0c))
    capas += _encima(plantilla, marca)
    final = capas[0][1].copy()
    for nombre, im, alfa, x, y in capas[1:]:
        if im.mode == "RGBA" and not cmyk:
            final.paste(im.convert("RGB"), (x, y), im.getchannel("A"))
        elif im.mode == "RGBA" and cmyk:
            final.paste(cmyk_de_capa(im), (x, y), im.getchannel("A"))
        else:
            final.paste(im, (x, y), alfa)
    return final, capas


def guardar_raster(im, ruta_sin_ext, formato, ppp=300):
    os.makedirs(os.path.dirname(ruta_sin_ext), exist_ok=True)
    if formato == "jpg":
        im = im if im.mode == "RGB" else color.cmyk_a_rgb(im)
        im.save(ruta_sin_ext + ".jpg", quality=95, subsampling=0, dpi=(ppp, ppp), icc_profile=color.icc_srgb())
        return ruta_sin_ext + ".jpg"
    if formato == "tif":
        icc = color.icc_fogra() if im.mode == "CMYK" else color.icc_srgb()
        im.save(ruta_sin_ext + ".tif", compression="tiff_lzw", dpi=(ppp, ppp), icc_profile=icc)
        return ruta_sin_ext + ".tif"
    raise ValueError(formato)


class PDFCopias:
    """PDF CMYK para imprimir en hojas de imprenta (SRA3): cada calendario centrado en su
    hoja, con sus copias seguidas (2 de cada jugador, 1 de cada entrenador...). La foto de
    las copias es la misma dentro del PDF, y se comprime al añadirla."""

    def __init__(self, ruta_sin_ext, hoja_mm, ppp=300, copias=None):
        os.makedirs(os.path.dirname(ruta_sin_ext), exist_ok=True)
        self.ruta = ruta_sin_ext + ".pdf"
        self.ppp = ppp
        self.hoja_px = [round(mm / 25.4 * ppp) for mm in hoja_mm]
        self.hoja_pt = [mm / 25.4 * 72 for mm in hoja_mm]
        self.copias = copias or {}
        self.pdf = fitz.open()

    def añadir(self, im, tipo="jugador"):
        """im: el calendario de una persona; tipo: su tipo (jugador, entrenador...)."""
        import zlib
        im = im if im.mode == "CMYK" else color.a_cmyk(im)
        W, H = self.hoja_px
        if im.width > W or im.height > H:
            raise ValueError(f"El calendario ({im.width} x {im.height} px) no cabe en la hoja ({W} x {H} px).")
        k = 72 / self.ppp
        x, y = (W - im.width) / 2 * k, (H - im.height) / 2 * k
        r = fitz.Rect(x, y, x + im.width * k, y + im.height * k)
        xref = 0
        for _ in range(self.copias.get(tipo, self.copias.get("jugador", 1))):
            pg = self.pdf.new_page(width=self.hoja_pt[0], height=self.hoja_pt[1])
            if xref:
                pg.insert_image(r, xref=xref)         # la misma foto: no ocupa más
                continue
            # CMYK sin JPEG (con JPEG CMYK hay programas que la ven en negativo)
            pix = fitz.Pixmap(fitz.csCMYK, im.width, im.height, im.tobytes(), False)
            xref = pg.insert_image(r, pixmap=pix, keep_proportion=False)
            del pix
            self.pdf.update_stream(xref, zlib.compress(self.pdf.xref_stream_raw(xref), 6), compress=False)
            self.pdf.xref_set_key(xref, "Filter", "/FlateDecode")
            self.pdf.xref_set_key(xref, "DecodeParms", "null")

    def cerrar(self):
        self.pdf.save(self.ruta, garbage=3, deflate=True)
        return self.ruta


class _CanalHecho:
    """Canal de una capa del TIFF ya comprimido al añadir la capa (así no se guardan en
    memoria todas las capas sin comprimir hasta el final)."""

    def __new__(cls, canal, formato):
        info, datos = canal.tobytes(formato)
        canal.data = None
        canal.tobytes = lambda *a, **k: (info, datos)
        return canal


class TIFFPorCapas:
    """TIFF de Photoshop con capas (como la plantilla del calendario de pared): la imagen
    compuesta y, dentro, las capas (abajo el fondo, una por jugador y arriba el escudo).
    Lo abren Photoshop, Affinity y Krita. Misma forma de uso que PSDPorCapas."""

    def __init__(self, tam, modo):
        import psdtags as P
        self.P = P
        self.tam, self.modo = tam, modo
        self.formato = P.PsdFormat.LE32BIT
        self.capas = []

    def añadir(self, nombre, im, alfa, x, y):
        P = self.P
        if self.modo == "CMYK":
            if im.mode != "CMYK":
                a = im.getchannel("A") if im.mode == "RGBA" else alfa
                im = cmyk_de_capa(im)
                alfa = a
            arr = 255 - np.asarray(im)          # Photoshop guarda el CMYK de las capas invertido
        else:
            if im.mode == "RGBA" and alfa is None:
                alfa = im.getchannel("A")
            arr = np.asarray(im.convert("RGB"))
        h, w = arr.shape[:2]
        ids = [P.PsdChannelId.CHANNEL0, P.PsdChannelId.CHANNEL1, P.PsdChannelId.CHANNEL2,
               P.PsdChannelId.CHANNEL3][:arr.shape[2]]
        canales = [P.PsdChannel(P.PsdChannelId.TRANSPARENCY_MASK, P.PsdCompressionType.ZIP,
                                np.ascontiguousarray(np.asarray(alfa, np.uint8) if alfa is not None
                                                     else np.full((h, w), 255, np.uint8)))]
        canales += [P.PsdChannel(c, P.PsdCompressionType.ZIP, np.ascontiguousarray(arr[:, :, i]))
                    for i, c in enumerate(ids)]
        self.capas.append(P.PsdLayer(
            name=nombre.encode("latin-1", "replace").decode("latin-1")[:31],
            rectangle=P.PsdRectangle(y, x, y + h, x + w),
            channels=[_CanalHecho(c, self.formato) for c in canales],
            mask=P.PsdLayerMask(), opacity=255, flags=P.PsdLayerFlag.PHOTOSHOP5,
            info=[P.PsdString(P.PsdKey.UNICODE_LAYER_NAME, nombre)]))

    def guardar(self, ruta, final):
        """final: la imagen compuesta (la que se ve al abrirlo sin mirar las capas)."""
        import tifffile
        P = self.P
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        cmyk = self.modo == "CMYK"
        f = final if final.mode == self.modo else (color.a_cmyk(final) if cmyk else color.cmyk_a_rgb(final))
        fuente = P.TiffImageSourceData(
            name="Publifoto", psdformat=self.formato,
            layers=P.PsdLayers(key=P.PsdKey.LAYER, has_transparency=False, layers=self.capas),
            usermask=P.PsdUserMask(colorspace=P.PsdColorSpaceType.RGB, components=(65535, 0, 0, 0),
                                   opacity=50))
        icc = color.icc_fogra() if cmyk else color.icc_srgb()
        tifffile.imwrite(ruta + ".tif", np.asarray(f), byteorder="<",
                         photometric="separated" if cmyk else "rgb", compression="adobe_deflate",
                         resolution=(300, 300), resolutionunit="INCH", metadata=None,
                         extratags=[fuente.tifftag(), (34675, 7, None, icc, True)])
        return ruta + ".tif"


class PSDPorCapas:
    """PSD por capas: se abre en Photoshop, Affinity, GIMP, Krita, Photopea...
    Las capas se pueden ir añadiendo según están listas (el calendario de pared junta a
    todos los jugadores) y se guarda al final."""

    def __init__(self, tam, modo):
        from psd_tools import PSDImage
        self.modo = modo
        self.psd = PSDImage.new(modo, tam)

    def añadir(self, nombre, im, alfa, x, y):
        from psd_tools.api.layers import PixelLayer
        from psd_tools.constants import Compression
        if self.modo == "CMYK":
            if im.mode != "CMYK":
                a = im.getchannel("A") if im.mode == "RGBA" else alfa
                im = cmyk_de_capa(im)
                alfa = a
            arr = 255 - np.asarray(im)
            if alfa is not None:
                arr = np.dstack([arr, np.asarray(alfa)])
            PixelLayer.fromarray(np.ascontiguousarray(arr), self.psd, nombre, top=y, left=x,
                                 compression=Compression.RLE)
        else:
            if alfa is not None:
                im = im.convert("RGB")
                im.putalpha(alfa)
            PixelLayer.frompil(im, self.psd, nombre, top=y, left=x, compression=Compression.RLE)

    def guardar(self, ruta, final=None):
        """final: la imagen ya compuesta (la de impresión). Si se da, es la vista previa
        del PSD y psd_tools no tiene que volver a componer todas las capas (lo más lento)."""
        from psd_tools.api import numpy_io
        psd = self.psd
        os.makedirs(os.path.dirname(ruta), exist_ok=True)
        if final is not None:
            f = final if final.mode == self.modo else (color.a_cmyk(final) if self.modo == "CMYK"
                                                        else color.cmyk_a_rgb(final))
            a = np.asarray(f, np.float32) / 255
            if self.modo == "CMYK":
                a = 1 - a          # el PSD guarda el CMYK invertido
            alfa_total = np.ones(a.shape[:2] + (1,), np.float32)
            psd._update_preview = lambda: psd._record.image_data.set_data(
                numpy_io.encode_image_data(psd, a, alfa_total), psd._record.header)
        psd.save(ruta + ".psd")
        return ruta + ".psd"


def guardar_psd(capas, tam, modo, ruta, final=None):
    psd = PSDPorCapas(tam, modo)
    for c in capas:
        psd.añadir(*c)
    return psd.guardar(ruta, final)


# --- productos PDF (imanes, sobremesa) ---------------------------------------

def _jpeg(im, cmyk):
    b = io.BytesIO()
    if cmyk:
        color.a_cmyk(im).save(b, "JPEG", quality=95, icc_profile=color.icc_fogra())
    else:
        im.convert("RGB").save(b, "JPEG", quality=95, icc_profile=color.icc_srgb())
    return b.getvalue()


def _escudo_en_pdf(doc, escudo, cmyk):
    """Cambia el escudo de la plantilla (las imágenes que quedan en el fondo, como la
    marca de agua del calendario de sobremesa) por el del club. Se sustituye la imagen
    misma: conserva su sitio, su tamaño y la transparencia del diseño. El logo nuevo
    va centrado y sin deformar dentro del rectángulo del antiguo."""
    from .club import ajustado
    hechos = set()
    for pg in doc:
        for img in pg.get_images(full=True):
            xref, smask, w, h = img[0], img[1], img[2], img[3]
            if xref in hechos:
                continue
            hechos.add(xref)
            logo = ajustado(escudo, (w, h))
            alfa = logo.getchannel("A")
            blanco = Image.new("RGB", logo.size, (255, 255, 255))
            blanco.paste(logo.convert("RGB"), mask=alfa)
            pix = color.a_cmyk(blanco) if cmyk else blanco
            doc.update_stream(xref, pix.tobytes(), compress=True)
            for clave in ("DecodeParms", "Decode", "Metadata"):
                doc.xref_set_key(xref, clave, "null")
            doc.xref_set_key(xref, "Filter", "/FlateDecode")
            doc.xref_set_key(xref, "BitsPerComponent", "8")
            if not cmyk:
                doc.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
            if smask:
                doc.update_stream(smask, alfa.tobytes(), compress=True)
                for clave in ("DecodeParms", "Decode", "Matte", "Metadata"):
                    doc.xref_set_key(smask, clave, "null")
                doc.xref_set_key(smask, "Filter", "/FlateDecode")
            else:
                m = doc.get_new_xref()
                doc.update_object(m, f"<< /Type /XObject /Subtype /Image /Width {w} /Height {h} "
                                     "/ColorSpace /DeviceGray /BitsPerComponent 8 >>")
                doc.update_stream(m, alfa.tobytes(), compress=True)
                doc.xref_set_key(xref, "SMask", f"{m} 0 R")


def _abrir_fondo(plantilla, archivo, marca):
    d = fitz.open(os.path.join(plantilla["_carpeta"], archivo))
    escudo = (marca or {}).get("escudo")
    if plantilla.get("escudo_pdf") and escudo:
        _escudo_en_pdf(d, escudo, plantilla["color"] == "CMYK")
    return d


def fotos_pdf(plantilla, hojas_jugadores, ajustes, hilos=None):
    """Las fotos ya recortadas de todos los huecos, {(hoja, hueco): imagen}. Con 'hilos'
    (un ThreadPoolExecutor) se hacen varias a la vez. Sirven para el PDF de impresión y
    para el editable: cada foto se recorta una sola vez."""
    ppp = plantilla.get("ppp_fotos", 300)
    tareas = []
    for n, jugadores in enumerate(hojas_jugadores):
        for k, (rect, _, j) in enumerate(colocacion(plantilla, jugadores)):
            r = fitz.Rect(rect)
            tam = (int(round(r.width / 72 * ppp)), int(round(r.height / 72 * ppp)))
            tareas.append(((n, k), j, tam))
    hacer = lambda t: foto_recortada(t[1], plantilla, t[2], ajustes.get(t[1].id))
    ims = list(hilos.map(hacer, tareas)) if hilos else [hacer(t) for t in tareas]
    return {t[0]: im for t, im in zip(tareas, ims)}


def pdf(plantilla, hojas_jugadores, equipo, ajustes, capas=False, carpeta_recortes=None, marca=None, fotos=None):
    """Crea el documento PDF completo (todas las hojas). Con capas=True cada parte
    va en su capa (Jugadores, Diseño, Texto) para editarla. Si se da
    carpeta_recortes, guarda ahí cada foto ya recortada al marco."""
    fondo = _abrir_fondo(plantilla, plantilla["fondo"], marca)
    valores = textos_marca(marca)
    cmyk = plantilla["color"] == "CMYK"
    ppp = plantilla.get("ppp_fotos", 300)
    doc = fitz.open()
    oc = {}
    if capas:
        for n in ("Jugadores", "Diseño", "Texto"):
            oc[n] = doc.add_ocg(n, on=True)
    for n, jugadores in enumerate(hojas_jugadores):
        pg = doc.new_page(width=fondo[0].rect.width, height=fondo[0].rect.height)
        for k, (rect, espejo, j) in enumerate(colocacion(plantilla, jugadores)):
            r = fitz.Rect(rect)
            tam = (int(round(r.width / 72 * ppp)), int(round(r.height / 72 * ppp)))
            im = fotos[(n, k)] if fotos else foto_recortada(j, plantilla, tam, ajustes.get(j.id))
            if espejo:
                im = im.transpose(Image.FLIP_TOP_BOTTOM)
            if carpeta_recortes:
                _guardar_recorte(im, espejo, j, carpeta_recortes)
            if cmyk:
                # CMYK sin JPEG: con JPEG CMYK, MuPDF marca los colores como invertidos
                # (/Decode) e Illustrator los vuelve a invertir: la foto sale en negativo
                c = color.a_cmyk(im)
                pix = fitz.Pixmap(fitz.csCMYK, c.width, c.height, c.tobytes(), False)
                pg.insert_image(r, pixmap=pix, keep_proportion=False, oc=oc.get("Jugadores", 0))
            else:
                pg.insert_image(r, stream=_jpeg(im, cmyk), keep_proportion=False, oc=oc.get("Jugadores", 0))
        # el diseño va encima de las fotos (marcos rojos incluidos)
        # hoja incompleta: fondo sin los calendarios que no llevan jugador
        parcial = plantilla.get("fondos_parciales", {}).get(str(len(jugadores)))
        diseño = _abrir_fondo(plantilla, parcial, marca) if parcial else fondo
        pg.show_pdf_page(pg.rect, diseño, 0, oc=oc.get("Diseño", 0))
        for i, t in enumerate(plantilla.get("textos", [])):
            texto = t["texto"].format(EQUIPO=equipo, **valores)
            fuente = ruta_fuente(t["fuente"])
            f = fitz.Font(fontfile=fuente)
            tam = t["tam"]
            ancho = f.text_length(texto, fontsize=tam)
            if t.get("largo_max") and ancho > t["largo_max"]:
                # nombres de club largos: la letra se reduce para que quepa en la franja
                tam *= t["largo_max"] / ancho
                ancho = t["largo_max"]
            if t.get("giro") == 90:
                # de abajo arriba, centrado en centro_y; base_x es la línea base
                pg.insert_text((t["base_x"], t["centro_y"] + ancho / 2), texto, fontsize=tam, rotate=90,
                               fontfile=fuente, fontname=f"t{i}", color=t["color"], oc=oc.get("Texto", 0))
            else:
                pg.insert_text((t["centro_x"] - ancho / 2, t["base_y"]), texto, fontsize=tam,
                               fontfile=fuente, fontname=f"t{i}", color=t["color"], oc=oc.get("Texto", 0))
    return doc


def _guardar_recorte(im, espejo, j, carpeta):
    """Como en InDesign: <foto>.jpg (delantera) y <foto>_DALT.jpg (trasera). La
    trasera va en espejo horizontal porque su marco está girado 180°."""
    os.makedirs(carpeta, exist_ok=True)
    if espejo:
        im = im.transpose(Image.ROTATE_180)   # reflejo vertical + giro 180° = espejo horizontal
        nombre = j.nombre + "_DALT.jpg"
    else:
        nombre = j.nombre + ".jpg"
    im.convert("RGB").save(os.path.join(carpeta, nombre), quality=95, dpi=(300, 300), icc_profile=color.icc_srgb())


_comprimidas = {}


def _comprimir_fotos(doc, hilos=None):
    """Comprime las fotos del PDF que van sin comprimir (las CMYK), varias a la vez.
    Al guardar, MuPDF lo haría de una en una y es lo más lento de los PDF. La misma foto
    del PDF de impresión y del editable se comprime una sola vez."""
    import hashlib
    import zlib
    pendientes = []
    for x in range(1, doc.xref_length()):
        if doc.xref_get_key(x, "Subtype")[1] == "/Image" and doc.xref_get_key(x, "Filter")[0] == "null":
            datos = doc.xref_stream_raw(x)
            pendientes.append((x, hashlib.md5(datos).hexdigest(), datos))
    nuevas = {h: d for _, h, d in pendientes if h not in _comprimidas}
    hacer = lambda hd: (hd[0], zlib.compress(hd[1], 6))
    for h, z in (hilos.map(hacer, nuevas.items()) if hilos else map(hacer, nuevas.items())):
        _comprimidas[h] = z
    for x, h, _ in pendientes:
        doc.update_stream(x, _comprimidas[h], compress=False)
        doc.xref_set_key(x, "Filter", "/FlateDecode")
        doc.xref_set_key(x, "DecodeParms", "null")


def guardar_pdf(doc, ruta_sin_ext, formato="pdf", hilos=None):
    """formato «ai»: el mismo PDF por capas con extensión .ai, que Illustrator abre como
    documento editable (un .ai de Illustrator es un PDF por dentro)."""
    os.makedirs(os.path.dirname(ruta_sin_ext), exist_ok=True)
    _comprimir_fotos(doc, hilos)
    ruta = ruta_sin_ext + (".ai" if formato == "ai" else ".pdf")
    doc.save(ruta, garbage=3, deflate=True)
    return ruta


def pdf_a_tif(doc, ruta_sin_ext, ppp=300):
    """Cada página en TIFF CMYK (FOGRA39), para imprimir sin pasar por el PDF."""
    salidas = []
    for i, pg in enumerate(doc):
        pix = pg.get_pixmap(dpi=ppp, colorspace=fitz.csCMYK)
        im = Image.frombytes("CMYK", (pix.width, pix.height), pix.samples)
        sufijo = "" if len(doc) == 1 else f" {i + 1}"
        salidas.append(guardar_raster(im, ruta_sin_ext + sufijo, "tif", ppp))
    return salidas


def pdf_a_jpg(doc, ruta_sin_ext, ppp=300):
    salidas = []
    for i, pg in enumerate(doc):
        pix = pg.get_pixmap(dpi=ppp, colorspace=fitz.csRGB)
        im = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        sufijo = "" if len(doc) == 1 else f" {i + 1}"
        salidas.append(guardar_raster(im, ruta_sin_ext + sufijo, "jpg", ppp))
    return salidas

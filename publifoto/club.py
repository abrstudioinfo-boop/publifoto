"""Escudo y nombre del club de cada equipo, y la carpeta de datos del programa.

Los logos se copian una vez a la carpeta de datos (botón «Añadir logos…»): uno por
club, con el nombre del club como nombre de archivo. Al generar, el escudo elegido
sustituye al de la plantilla en 15 x 20, calendario de pared y calendario de
sobremesa; en los imanes va el nombre del club y la temporada.
"""
import datetime
import json
import os
import sys

from PIL import Image

Image.MAX_IMAGE_PIXELS = None
EXTENSIONES = (".png", ".tif", ".tiff", ".jpg", ".jpeg", ".webp")
LADO_MAX = 2500   # px: los logos más grandes se reducen al copiarlos (de sobra para 300 ppp)


def carpeta_datos():
    """Carpeta del usuario donde se guardan los logos y las plantillas actualizadas
    (dentro del programa montado no se puede escribir, y en el Mac menos)."""
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support/Publifoto")
    elif os.name == "nt":
        base = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "Publifoto", "datos")
    else:
        base = os.path.expanduser("~/.local/share/Publifoto")
    return base


def carpeta_logos():
    return os.path.join(carpeta_datos(), "logos")


def _nombres():
    try:
        with open(os.path.join(carpeta_logos(), "nombres.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def lista_logos():
    """[(nombre del club, ruta del logo)] por orden alfabético."""
    c = carpeta_logos()
    if not os.path.isdir(c):
        return []
    return sorted(((os.path.splitext(f)[0], os.path.join(c, f)) for f in os.listdir(c)
                   if f.lower().endswith(".png")), key=lambda x: x[0].lower())


def importar_logos(carpeta):
    """Copia los logos de una carpeta a la del programa (como PNG con transparencia,
    sin márgenes vacíos). Devuelve los nombres añadidos."""
    os.makedirs(carpeta_logos(), exist_ok=True)
    nuevos = []
    for f in sorted(os.listdir(carpeta)):
        if not f.lower().endswith(EXTENSIONES) or f.startswith("."):
            continue
        nombre = os.path.splitext(f)[0].strip()
        try:
            im = Image.open(os.path.join(carpeta, f))
            im.load()
        except OSError:
            continue
        im = limpiar(im)
        im.save(os.path.join(carpeta_logos(), nombre + ".png"))
        nuevos.append(nombre)
    return nuevos


def borrar_logo(nombre):
    ruta = os.path.join(carpeta_logos(), nombre + ".png")
    if os.path.exists(ruta):
        os.remove(ruta)


def limpiar(im):
    """Logo en RGBA, sin el margen transparente de alrededor y como mucho LADO_MAX px."""
    if im.mode in ("CMYK", "P", "LA", "L", "RGB", "I;16"):
        from .color import a_rgb
        tiene_alfa = im.mode in ("LA", "P") and ("transparency" in im.info or im.mode == "LA")
        im = im.convert("RGBA") if tiene_alfa else a_rgb(im).convert("RGBA")
    elif im.mode != "RGBA":
        im = im.convert("RGBA")
    caja = im.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox()
    if caja:
        im = im.crop(caja)
    if max(im.size) > LADO_MAX:
        im.thumbnail((LADO_MAX, LADO_MAX), Image.LANCZOS)
    return im


def ajustado(ruta, tam, fondo=(0, 0, 0, 0)):
    """El logo centrado y lo más grande posible dentro de un rectángulo de 'tam' px,
    sin deformarlo. Devuelve una imagen RGBA de ese tamaño."""
    im = Image.open(ruta)
    im.load()
    im = limpiar(im)
    W, H = int(tam[0]), int(tam[1])
    k = min(W / im.width, H / im.height)
    w, h = max(1, round(im.width * k)), max(1, round(im.height * k))
    im = im.resize((w, h), Image.LANCZOS)
    lienzo = Image.new("RGBA", (W, H), fondo)
    lienzo.alpha_composite(im, ((W - w) // 2, (H - h) // 2))
    return lienzo


def texto_club(nombre):
    """Nombre del club que se imprime en los imanes: el guardado para ese logo o, si
    no hay, el nombre del archivo en mayúsculas."""
    return _nombres().get(nombre) or nombre.upper()


def guardar_texto_club(nombre, texto):
    d = _nombres()
    d[nombre] = texto
    os.makedirs(carpeta_logos(), exist_ok=True)
    with open(os.path.join(carpeta_logos(), "nombres.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def temporada_actual(hoy=None):
    """Temporada de fútbol: de julio a junio («26/27» entre julio de 2026 y junio de 2027)."""
    hoy = hoy or datetime.date.today()
    a = hoy.year if hoy.month >= 7 else hoy.year - 1
    return f"{a % 100:02d}/{(a + 1) % 100:02d}"

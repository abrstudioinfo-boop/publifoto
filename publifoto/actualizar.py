"""Actualizar una plantilla desde el programa (por ejemplo, el calendario de sobremesa
de cada año): se elige el archivo nuevo, se convierte como las de dentro del programa,
se prueba generando el producto con figuras dibujadas y, solo si sale bien, sustituye
a la que había. La plantilla del programa no se toca: «Volver a la original» la recupera.
"""
import datetime
import json
import os
import shutil
import tempfile

from . import productos

# qué archivo pide cada plantilla
ACTUALIZABLES = {
    "sobremesa": ("Calendario de sobremesa", "PDF exportado de InDesign (*.pdf)",
                  "El PDF del calendario con las fotos de ejemplo. El .indd no se puede leer sin "
                  "Adobe: en InDesign, Archivo > Exportar > PDF para impresión."),
    "imanes": ("Imanes", "Illustrator o PDF (*.ai *.pdf)",
               "El .ai de los imanes con las fotos de ejemplo y el texto «S10 A» del equipo."),
    "pared": ("Calendario de pared", "TIFF con capas (*.tif *.tiff)",
              "El TIFF de Photoshop con capas: fotos de ejemplo y la capa del escudo."),
    "15x20": ("15 x 20 con logo", "TIFF con capas (*.tif *.tiff)",
              "El TIFF de Photoshop con capas: foto de ejemplo y la capa del escudo."),
    "cartas": ("Cartas", "TIFF con capas (*.tif *.tiff)",
               "El TIFF de Photoshop de la carta con los colores del equipo, con sus capas y un jugador "
               "de ejemplo en «Place Your Image Here». Es un archivo grande: tarda un par de minutos."),
}


ORIGINAL = "La que viene con el programa"


def propia(id_):
    """¿Hay una copia de la plantilla en la carpeta del usuario (actualizada o con el
    encuadre cambiado)?"""
    return os.path.exists(os.path.join(productos.carpeta_plantillas_usuario(), id_, "plantilla.json"))


def info(id_):
    """Texto con la plantilla que se está usando."""
    marca = os.path.join(productos.carpeta_plantillas_usuario(), id_, "actualizada.json")
    if os.path.exists(marca):
        with open(marca, encoding="utf-8") as f:
            d = json.load(f)
        return f"Actualizada el {d['fecha']} con «{d['archivo']}»"
    if propia(id_):
        return ORIGINAL + ", con el encuadre cambiado"
    return ORIGINAL


def guardar_encuadre(id_, enc):
    """Guarda el encuadre predeterminado del producto (cuánto ocupa el jugador en el
    hueco). Si la plantilla es la del programa, se copia antes a la carpeta del
    usuario: la del programa no se toca y «Volver a la original» la recupera."""
    carpeta = os.path.join(productos.carpeta_plantillas_usuario(), id_)
    if not propia(id_):
        shutil.rmtree(carpeta, ignore_errors=True)
        shutil.copytree(os.path.join(productos.PLANTILLAS, id_), carpeta)
    ruta = os.path.join(carpeta, "plantilla.json")
    with open(ruta, encoding="utf-8") as f:
        p = json.load(f)
    p["encuadre"] = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in enc.items()}
    with open(ruta, "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)


def _resumen(p):
    if p["tipo"] == "carta":
        return f"carta de {p['lienzo'][0]} x {p['lienzo'][1]} px"
    if "marcos" in p:
        return f"{len(p['marcos'])} marcos para fotos, archivo «{p['archivo']}»"
    if p.get("huecos") and p["tipo"] == "pdf":
        return f"{len(p['huecos'])} imanes por hoja"
    return f"lienzo de {p['lienzo'][0]} x {p['lienzo'][1]} px con escudo"


def actualizar(id_, origen, progreso=print):
    """Prepara la plantilla id_ desde 'origen', la prueba y la pone en uso.
    Devuelve un resumen; si algo falla lanza ValueError y deja la que había."""
    from .comprobar import prueba_completa
    from .herramientas import preparar_plantillas
    if id_ not in ACTUALIZABLES:
        raise ValueError(f"La plantilla {id_} no se puede actualizar desde aquí.")
    if origen.lower().endswith(".indd"):
        raise ValueError(ACTUALIZABLES[id_][2])
    base = productos.carpeta_plantillas_usuario()
    nueva, final, anterior = (os.path.join(base, n) for n in (f"_nueva_{id_}", id_, f"_anterior_{id_}"))
    for c in (nueva, anterior):
        shutil.rmtree(c, ignore_errors=True)
    progreso("Convirtiendo la plantilla...")
    try:
        preparar_plantillas.preparar(id_, origen, nueva)
    except Exception as e:
        shutil.rmtree(nueva, ignore_errors=True)
        raise ValueError(f"No se ha podido convertir: {e}") from e
    vieja = productos.cargar_plantilla(id_)
    with open(os.path.join(nueva, "plantilla.json"), encoding="utf-8") as f:
        p = json.load(f)
    # el jugador sale como en la plantilla de antes (después se puede cambiar)
    p["encuadre"] = vieja["encuadre"]
    if id_ == "cartas" and vieja.get("variantes"):
        # los colores de los otros clubs siguen con la carta nueva
        # (las que vienen con el programa se añaden solas al abrirla: no se copian)
        p["variantes"] = {k: v for k, v in vieja["variantes"].items() if "_ruta" not in v}
        if os.path.isdir(os.path.join(vieja["_carpeta"], "variantes")):
            shutil.copytree(os.path.join(vieja["_carpeta"], "variantes"), os.path.join(nueva, "variantes"),
                            dirs_exist_ok=True)
    with open(os.path.join(nueva, "plantilla.json"), "w", encoding="utf-8") as f:
        json.dump(p, f, ensure_ascii=False, indent=2)
    # se pone en uso y se prueba; si falla se vuelve a la de antes
    if os.path.exists(final):
        os.replace(final, anterior)
    os.replace(nueva, final)
    progreso("Probando la plantilla nueva con figuras dibujadas...")
    carpeta_prueba = tempfile.mkdtemp(prefix="publifoto_plantilla_")
    try:
        bien = prueba_completa(carpeta_prueba, jugadores=3, entrenadores=1, productos=[id_])
    except Exception as e:
        bien = False
        progreso(f"  error: {e}")
    if not bien:
        shutil.rmtree(final, ignore_errors=True)
        if os.path.exists(anterior):
            os.replace(anterior, final)
        shutil.rmtree(carpeta_prueba, ignore_errors=True)
        raise ValueError("La plantilla nueva no genera bien el producto: se sigue usando la anterior.")
    with open(os.path.join(final, "actualizada.json"), "w", encoding="utf-8") as f:
        json.dump({"archivo": os.path.basename(origen), "fecha": datetime.date.today().strftime("%d/%m/%Y")},
                  f, ensure_ascii=False)
    shutil.rmtree(anterior, ignore_errors=True)
    avisos = []
    if vieja.get("huecos") and p.get("huecos") and len(vieja["huecos"]) != len(p["huecos"]):
        avisos.append(f"Antes había {len(vieja['huecos'])} huecos y ahora {len(p['huecos'])}.")
    vista = _vista_previa(carpeta_prueba)
    return {"id": id_, "resumen": _resumen(p), "avisos": avisos, "vista": vista, "carpeta_prueba": carpeta_prueba}


def _vista_previa(carpeta):
    """Primera página o imagen generada en la prueba, como PNG pequeño."""
    import pymupdf as fitz
    from PIL import Image
    for raiz, _, archivos in os.walk(carpeta):
        if os.path.basename(raiz) != "IMPRESION":
            continue
        for a in sorted(archivos):
            ruta = os.path.join(raiz, a)
            salida = os.path.join(carpeta, "vista.png")
            if a.lower().endswith(".pdf"):
                fitz.open(ruta)[0].get_pixmap(dpi=40).save(salida)
                return salida
            if a.lower().endswith((".jpg", ".tif")):
                from .color import a_rgb
                im = a_rgb(Image.open(ruta))
                im.thumbnail((500, 500))
                im.save(salida)
                return salida
    return None


def restaurar(id_):
    """Vuelve a la plantilla que viene con el programa."""
    shutil.rmtree(os.path.join(productos.carpeta_plantillas_usuario(), id_), ignore_errors=True)

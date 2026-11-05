"""Motor: de una carpeta de fotos arregladas a todos los productos del equipo.

Estructura de salida:
    <salida>/<EQUIPO>/<PRODUCTO>/IMPRESION/...
    <salida>/<EQUIPO>/<PRODUCTO>/EDITABLE/...
    <salida>/<EQUIPO>/<EQUIPO>.publifoto   (proyecto para corregir y regenerar)
"""
import json
import os
from dataclasses import dataclass, field

from . import productos
from .analisis import analizar

EXTENSIONES = (".jpg", ".jpeg", ".png", ".tif", ".tiff")
UMBRAL_GRIS = 0.08   # ropa gris -> entrenador


@dataclass
class Jugador:
    ruta: str
    puntos: object = None
    tipo: str = "jugador"          # jugador | entrenador | equipo
    incluido: bool = True
    ruta_recorte: str = None       # PNG sin fondo (solo cartas)
    giro: float = 0.0              # grados (antihorario) para enderezarlo, en todos los productos
    tipo_manual: bool = False      # el operario ha elegido el tipo: los revisores no lo tocan
    tipo_seguro: bool = True
    marcas: object = None          # puntos de cara y cuerpo (marcas.py)
    giro_auto: float = 0.0         # enderezado de la cabeza en los primeros planos (revision.py)
    giro_dudoso: bool = False
    sin_giro_auto: bool = False    # el operario ha quitado el giro automático
    revisados: list = field(default_factory=list)   # revisores cuyos avisos ya ha mirado el operario
    retoque: list = field(default_factory=list)     # granos y rojeces a quitar (retoque.py)
    sin_retoque: bool = False      # el operario ha quitado el retoque de piel de esta foto
    retocar: bool = True           # retoque activo al generar (lo pone el trabajo)

    @property
    def id(self):
        return os.path.basename(self.ruta)

    @property
    def nombre(self):
        return os.path.splitext(self.id)[0]


@dataclass
class Trabajo:
    equipo: str
    carpeta_fotos: str
    carpeta_salida: str
    carpeta_recortes: str = None
    productos: list = field(default_factory=list)
    jugadores: list = field(default_factory=list)
    ajustes: dict = field(default_factory=dict)   # {producto: {foto: {dx, dy, zoom}}}
    avisos: list = field(default_factory=list)    # de los revisores automáticos
    escudo: str = None        # logo del club (club.py); None = el de la plantilla
    club: str = None          # nombre del club en los imanes; None = el de la plantilla
    temporada: str = None     # «26/27»; None = la temporada actual
    retocar_piel: bool = True # quitar granos y rojeces notables (retoque.py)
    subcarpeta: bool = True   # False: los productos van directamente en carpeta_salida
                              # (la carpeta arrastrada); True: en carpeta_salida/<equipo>

    @property
    def marca(self):
        return {"escudo": self.escudo if self.escudo and os.path.exists(self.escudo) else None,
                "club": self.club, "temporada": self.temporada}

    @property
    def carpeta_equipo(self):
        if not self.subcarpeta:
            return self.carpeta_salida
        return os.path.join(self.carpeta_salida, self.equipo)

    @property
    def ruta_proyecto(self):
        return os.path.join(self.carpeta_equipo, self.equipo + ".publifoto")


def buscar_fotos(carpeta):
    return sorted(os.path.join(carpeta, f) for f in os.listdir(carpeta)
                  if f.lower().endswith(EXTENSIONES) and not f.startswith("."))


def preparar(trabajo, progreso=print):
    """Analiza las fotos y pasa los revisores automáticos: corrigen la silueta, enderezan
    la cabeza en los primeros planos y clasifican jugadores, entrenadores y foto de equipo."""
    from . import revision
    fotos = buscar_fotos(trabajo.carpeta_fotos)
    recortes = {}
    if trabajo.carpeta_recortes and os.path.isdir(trabajo.carpeta_recortes):
        recortes = {os.path.splitext(os.path.basename(r))[0]: r for r in buscar_fotos(trabajo.carpeta_recortes)
                    if r.lower().endswith(".png")}
    previos = {j.id: j for j in trabajo.jugadores}
    trabajo.jugadores = []
    avisos = []
    for i, ruta in enumerate(fotos):
        progreso(f"Analizando {os.path.basename(ruta)} ({i + 1}/{len(fotos)})")
        j = Jugador(ruta=ruta)
        sin_persona = False
        try:
            j.puntos = analizar(ruta)
        except ValueError:
            # foto en blanco o sin nadie: se deja fuera sin parar el resto del equipo
            from .analisis import Puntos, abrir
            w, h = abrir(ruta).size
            j.puntos = Puntos(w, h, 0.1, 0.2, 0.5, 0.5, 0.9, 0.0)
            sin_persona = True
            avisos.append(revision.Aviso(j.id, "calidad", "error",
                                         "No se encuentra a nadie en la foto: queda fuera."))
        if not sin_persona:
            avisos += revision.preparar_jugador(j)
            from . import retoque
            avisos += retoque.preparar_jugador(j)
        if j.id in previos:   # respetar lo que el operario ya decidió
            v = previos[j.id]
            j.incluido, j.giro, j.sin_giro_auto = v.incluido, v.giro, v.sin_giro_auto
            j.sin_retoque = v.sin_retoque
            j.revisados = list(v.revisados)
            if v.tipo_manual:
                j.tipo, j.tipo_manual = v.tipo, True
        if sin_persona:
            j.incluido = False
        j.ruta_recorte = recortes.get(j.nombre)
        trabajo.jugadores.append(j)
    progreso("Revisando clasificación...")
    avisos += revision.clasificar(trabajo.jugadores)
    for j in trabajo.jugadores:
        if j.id not in previos and j.incluido:
            j.incluido = j.tipo != "equipo"
    trabajo.avisos = filtrar_avisos(trabajo, avisos)
    return trabajo


def filtrar_avisos(trabajo, avisos):
    """Quita los avisos que el operario ya ha resuelto: tipo elegido a mano, giro puesto o
    quitado a mano, o avisos de un revisor que ya ha mirado."""
    por_id = {j.id: j for j in trabajo.jugadores}
    fuera = []
    for a in avisos:
        j = por_id.get(a.foto)
        if j is not None:
            if a.revisor == "clasificacion" and j.tipo_manual:
                continue
            if a.revisor == "inclinacion" and (j.sin_giro_auto or (a.nivel == "revisar" and j.giro)):
                continue
            if a.nivel == "revisar" and a.revisor in j.revisados:
                continue
        fuera.append(a)
    return fuera


def revisar_encuadres(trabajo):
    """Avisos de encuadre de los productos elegidos (se repite al cambiar de productos)."""
    from . import revision
    base = [a for a in trabajo.avisos if a.revisor not in ("encuadre", "presencia")]
    trabajo.avisos = filtrar_avisos(trabajo, base + revision.revisar_encuadres(trabajo))
    return trabajo.avisos


def comprobar(trabajo):
    """Avisos antes de generar (lista de textos)."""
    avisos = []
    if "cartas" in trabajo.productos:
        sin = [j.id for j in trabajo.jugadores if j.incluido and j.tipo == "jugador" and not j.ruta_recorte]
        if not trabajo.carpeta_recortes:
            avisos.append("Para CARTAS hace falta la carpeta de fotos RECORTADAS (PNG sin fondo).")
        elif sin:
            avisos.append("Faltan recortes para: " + ", ".join(sin))
    return avisos


PRODUCTOS_CON_ENTRENADORES = ("pared",)   # los entrenadores solo salen en el calendario de pared


def jugadores_para(trabajo, plantilla):
    # la regla de los entrenadores es del programa, no de la plantilla: así una plantilla
    # nueva (o una antigua de otro ordenador) no los mete donde no van
    excluir = set(plantilla.get("excluir", [])) | {"equipo"}
    if plantilla.get("id") in PRODUCTOS_CON_ENTRENADORES:
        excluir.discard("entrenador")
    else:
        excluir.add("entrenador")
    return [j for j in trabajo.jugadores if j.incluido and j.tipo not in excluir]


def generar(trabajo, progreso=print):
    salidas = []
    for j in trabajo.jugadores:
        j.retocar = trabajo.retocar_piel
    for id_ in trabajo.productos:
        p = productos.cargar_plantilla(id_)
        progreso(f"Generando {p['nombre']}...")
        jug = jugadores_para(trabajo, p)
        if not jug:
            continue
        aj = trabajo.ajustes.get(id_, {})
        base = os.path.join(trabajo.carpeta_equipo, p["nombre"])
        imp, edi = os.path.join(base, "IMPRESION"), os.path.join(base, "EDITABLE")
        if id_ == "cartas":
            from . import cartas
            salidas += cartas.generar(p, jug, trabajo.equipo, aj, imp, edi, progreso)
        elif p["tipo"] == "pdf":
            hs = productos.hojas(p, jug)
            nombre = productos.nombre_archivo(p, trabajo.equipo)
            doc = productos.pdf(p, hs, trabajo.equipo, aj, marca=trabajo.marca)
            if "pdf" in p["impresion"]:
                salidas.append(productos.guardar_pdf(doc, os.path.join(imp, nombre)))
            if "jpg" in p["impresion"]:
                salidas += productos.pdf_a_jpg(doc, os.path.join(imp, nombre))
            if "tif" in p["impresion"]:
                salidas += productos.pdf_a_tif(doc, os.path.join(imp, nombre))
            recortes = os.path.join(edi, "FOTOS") if p.get("guardar_recortes") else None
            salidas.append(productos.guardar_pdf(productos.pdf(p, hs, trabajo.equipo, aj, capas=True, marca=trabajo.marca,
                                                               carpeta_recortes=recortes),
                                                 os.path.join(edi, nombre)))
        else:
            salidas += _generar_raster(p, jug, trabajo, aj, imp, edi, progreso)
    guardar_proyecto(trabajo)
    from . import revision
    progreso("Revisando los archivos generados...")
    trabajo.avisos = [a for a in trabajo.avisos if a.revisor not in ("salida", "presencia")] + \
        revision.revisar_salida(trabajo, salidas)
    return salidas


def _generar_raster(p, jug, trabajo, aj, imp, edi, progreso):
    salidas = []
    una_por_jugador = p.get("jugadores_por_hoja", 1) == 1 and len(p["huecos"]) == 1
    if una_por_jugador:
        todas_capas = []
        for j in jug:
            progreso(f"  {p['nombre']}: {j.nombre}")
            final, capas = productos.raster(p, [j], trabajo.equipo, aj, marca=trabajo.marca)
            nombre = productos.nombre_archivo(p, trabajo.equipo, foto=j.nombre)
            for fmt in p["impresion"]:
                salidas.append(productos.guardar_raster(final, os.path.join(imp, nombre), fmt))
            if p["id"] == "pared":
                todas_capas.append(capas[1])   # la foto
                logo = capas[2:]
            else:
                salidas.append(productos.guardar_psd(capas, tuple(p["lienzo"]), p["color"], os.path.join(edi, nombre)))
        if p["id"] == "pared" and todas_capas:
            # como la plantilla original: un solo archivo con una capa por jugador
            capas = [("Fondo",) + tuple(capas[0][1:])] + todas_capas + logo
            nombre = productos.nombre_archivo(p, trabajo.equipo, foto="TODOS").replace(" - TODOS", "")
            salidas.append(productos.guardar_psd(capas, tuple(p["lienzo"]), p["color"], os.path.join(edi, nombre)))
    else:
        for n, hoja in enumerate(productos.hojas(p, jug), 1):
            progreso(f"  {p['nombre']}: hoja {n}")
            final, capas = productos.raster(p, hoja, trabajo.equipo, aj, n, marca=trabajo.marca)
            nombre = productos.nombre_archivo(p, trabajo.equipo, n=n)
            for fmt in p["impresion"]:
                salidas.append(productos.guardar_raster(final, os.path.join(imp, nombre), fmt))
            salidas.append(productos.guardar_psd(capas, tuple(p["lienzo"]), p["color"], os.path.join(edi, nombre)))
    return salidas


# --- proyecto ------------------------------------------------------------------

def guardar_proyecto(trabajo):
    os.makedirs(trabajo.carpeta_equipo, exist_ok=True)
    datos = {
        "version": 2, "equipo": trabajo.equipo, "escudo": trabajo.escudo, "club": trabajo.club,
        "temporada": trabajo.temporada, "carpeta_fotos": trabajo.carpeta_fotos,
        "carpeta_recortes": trabajo.carpeta_recortes, "carpeta_salida": trabajo.carpeta_salida,
        "subcarpeta": trabajo.subcarpeta, "retocar_piel": trabajo.retocar_piel,
        "productos": trabajo.productos, "ajustes": trabajo.ajustes,
        "jugadores": [{"foto": j.id, "tipo": j.tipo, "incluido": j.incluido, "giro": j.giro,
                       "tipo_manual": j.tipo_manual, "sin_giro_auto": j.sin_giro_auto,
                       "revisados": j.revisados, "sin_retoque": j.sin_retoque}
                      for j in trabajo.jugadores],
    }
    with open(trabajo.ruta_proyecto, "w", encoding="utf-8") as f:
        json.dump(datos, f, ensure_ascii=False, indent=2)


def abrir_proyecto(ruta, progreso=print):
    with open(ruta, encoding="utf-8") as f:
        d = json.load(f)
    t = Trabajo(equipo=d["equipo"], carpeta_fotos=d["carpeta_fotos"], carpeta_salida=d["carpeta_salida"],
                carpeta_recortes=d.get("carpeta_recortes"), productos=d["productos"], ajustes=d.get("ajustes", {}),
                escudo=d.get("escudo"), club=d.get("club"), temporada=d.get("temporada"),
                subcarpeta=d.get("subcarpeta", True), retocar_piel=d.get("retocar_piel", True))
    t.jugadores = []
    for x in d["jugadores"]:
        j = Jugador(ruta=os.path.join(t.carpeta_fotos, x["foto"]), tipo=x["tipo"], incluido=x["incluido"],
                    giro=x.get("giro", 0.0), sin_giro_auto=x.get("sin_giro_auto", False),
                    revisados=list(x.get("revisados", [])), sin_retoque=x.get("sin_retoque", False))
        if "tipo_manual" in x:
            j.tipo_manual = x["tipo_manual"]
        elif os.path.exists(j.ruta):
            # proyectos de la versión 1: el tipo es manual si no es el que habría puesto
            # la regla antigua (foto horizontal = equipo, ropa gris = entrenador)
            try:
                p = analizar(j.ruta)
            except ValueError:
                t.jugadores.append(j)
                continue
            antiguo = "equipo" if p.ancho > p.alto else ("entrenador" if p.gris > UMBRAL_GRIS else "jugador")
            j.tipo_manual = x["tipo"] != antiguo
        t.jugadores.append(j)
    return preparar(t, progreso)

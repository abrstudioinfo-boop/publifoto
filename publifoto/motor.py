"""Motor: de una carpeta de fotos arregladas a todos los productos del equipo.

Estructura de salida:
    <salida>/<EQUIPO>/<PRODUCTO>/IMPRESION/...
    <salida>/<EQUIPO>/<PRODUCTO>/EDITABLE/...
    <salida>/<EQUIPO>/<EQUIPO>.publifoto   (proyecto para corregir y regenerar)
"""
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
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
    ruta_recorte: str = None       # PNG sin fondo del cliente (cartas; si no hay, se recorta solo)
    carta: tuple = None            # (PNG recortado, colocación) para la carta (carta_auto.py)
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


# MuPDF (los PDF) no admite varios hilos a la vez: los productos PDF van de uno en uno
_PDF = threading.Lock()


def memoria_gb():
    """Memoria RAM del ordenador (GB), sin librerías extra; 8 si no se sabe."""
    try:
        if os.name == "nt":
            import ctypes

            class Estado(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            e = Estado()
            e.dwLength = ctypes.sizeof(Estado)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(e))
            return e.ullTotalPhys / 2 ** 30
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2 ** 30
    except Exception:
        return 8.0


def hilos_disponibles():
    """Fotos que se preparan a la vez: tantas como núcleos (menos uno), pero cada una
    ocupa hasta 1 GB de memoria, así que también según la RAM. Máximo 8."""
    return max(1, min(8, (os.cpu_count() or 2) - 1, int(memoria_gb() // 2)))


def generar(trabajo, progreso=print):
    """Genera los productos elegidos. Van a la vez (cada uno en su hilo) y, dentro de
    cada producto, se preparan varios jugadores a la vez; el resultado es el mismo que
    haciéndolos de uno en uno."""
    for j in trabajo.jugadores:
        j.retocar = trabajo.retocar_piel
    productos.limpiar_cache()
    if "cartas" in trabajo.productos:
        _recortar_cartas(trabajo, progreso)
    n = hilos_disponibles()
    with ThreadPoolExecutor(max_workers=n, thread_name_prefix="foto") as fotos, \
            ThreadPoolExecutor(max_workers=len(trabajo.productos) or 1, thread_name_prefix="producto") as prods:
        # todos empiezan a la vez (las fotos se reparten en 'fotos'); el calendario de pared
        # primero: es el que más tarda (al final junta a todos en un PSD)
        orden = sorted(trabajo.productos, key=lambda i: i != "pared")
        futuros = {id_: prods.submit(_generar_producto, trabajo, id_, progreso, fotos) for id_ in orden}
        salidas = [s for id_ in trabajo.productos for s in futuros[id_].result()]
    guardar_proyecto(trabajo)
    from . import revision
    progreso("Revisando los archivos generados...")
    trabajo.avisos = [a for a in trabajo.avisos if a.revisor not in ("salida", "presencia")] + \
        revision.revisar_salida(trabajo, salidas)
    return salidas


def _recortar_cartas(trabajo, progreso):
    """Recorta a los jugadores de las cartas antes de repartir el trabajo en hilos: el
    modelo de retrato usa él solo todos los núcleos. Lo ya recortado queda en la caché."""
    from . import carta_auto, revision
    jug = jugadores_para(trabajo, productos.cargar_plantilla("cartas"))
    trabajo.avisos = [a for a in trabajo.avisos if a.revisor != "recorte"]
    try:
        for i, j in enumerate(jug, 1):
            progreso(f"Recortando para cartas {j.nombre} ({i}/{len(jug)})")
            try:
                j.carta = carta_auto.preparar(j)
            except Exception as e:
                j.carta = None
                trabajo.avisos.append(revision.Aviso(j.id, "recorte", "error",
                                                     f"No se ha podido recortar para la carta: {e}", "cartas"))
    finally:
        carta_auto.liberar_modelo()


def _generar_producto(trabajo, id_, progreso, hilos):
    p = productos.cargar_plantilla(id_)
    jug = jugadores_para(trabajo, p)
    if not jug:
        return []
    progreso(f"Generando {p['nombre']}...")
    salidas = []
    aj = trabajo.ajustes.get(id_, {})
    base = os.path.join(trabajo.carpeta_equipo, p["nombre"])
    imp, edi = os.path.join(base, "IMPRESION"), os.path.join(base, "EDITABLE")
    if id_ == "cartas":
        from . import cartas
        salidas += cartas.generar(p, jug, trabajo.equipo, aj, imp, edi, progreso, hilos)
    elif p["tipo"] == "pdf":
        hs = productos.hojas(p, jug)
        nombre = productos.nombre_archivo(p, trabajo.equipo)
        fotos = productos.fotos_pdf(p, hs, aj, hilos)
        with _PDF:
            doc = productos.pdf(p, hs, trabajo.equipo, aj, marca=trabajo.marca, fotos=fotos)
            if "pdf" in p["impresion"]:
                salidas.append(productos.guardar_pdf(doc, os.path.join(imp, nombre), hilos=hilos))
            if "jpg" in p["impresion"]:
                salidas += productos.pdf_a_jpg(doc, os.path.join(imp, nombre))
            if "tif" in p["impresion"]:
                salidas += productos.pdf_a_tif(doc, os.path.join(imp, nombre))
            recortes = os.path.join(edi, "FOTOS") if p.get("guardar_recortes") else None
            salidas.append(productos.guardar_pdf(productos.pdf(p, hs, trabajo.equipo, aj, capas=True,
                                                               marca=trabajo.marca, carpeta_recortes=recortes,
                                                               fotos=fotos),
                                                 os.path.join(edi, nombre), p.get("editable", "pdf"), hilos))
    else:
        salidas += _generar_raster(p, jug, trabajo, aj, imp, edi, progreso, hilos)
    progreso(f"Hecho {p['nombre']}")
    return salidas


def _generar_raster(p, jug, trabajo, aj, imp, edi, progreso, hilos):
    salidas = []
    una_por_jugador = p.get("jugadores_por_hoja", 1) == 1 and len(p["huecos"]) == 1
    if una_por_jugador:
        def uno(j):
            progreso(f"  {p['nombre']}: {j.nombre}")
            final, capas = productos.raster(p, [j], trabajo.equipo, aj, marca=trabajo.marca)
            nombre = productos.nombre_archivo(p, trabajo.equipo, foto=j.nombre)
            hechos = [productos.guardar_raster(final, os.path.join(imp, nombre), fmt) for fmt in p["impresion"]]
            if p["id"] != "pared":
                hechos.append(productos.guardar_psd(capas, tuple(p["lienzo"]), p["color"], os.path.join(edi, nombre),
                                                    final))
                capas, final = None, None   # no hacen falta después: se libera la memoria
            return hechos, capas, final
        # calendario de pared: como la plantilla original, un solo PSD con una capa por
        # jugador; cada capa se añade en cuanto ese jugador está listo
        todos = productos.PSDPorCapas(tuple(p["lienzo"]), p["color"]) if p["id"] == "pared" else None
        for hechos, capas, ultima in hilos.map(uno, jug):     # en el orden de los jugadores
            salidas += hechos
            if todos is not None:
                if not todos.psd:
                    todos.añadir("Fondo", *capas[0][1:])
                todos.añadir(*capas[1])                    # la foto
                logo, final = capas[2:], ultima
        if todos is not None and len(todos.psd):
            for c in logo:
                todos.añadir(*c)
            nombre = productos.nombre_archivo(p, trabajo.equipo, foto="TODOS").replace(" - TODOS", "")
            # se ve el último jugador (la capa de arriba), como al componer las capas
            salidas.append(todos.guardar(os.path.join(edi, nombre), final))
    else:
        def hoja(n_hoja):
            n, jugadores = n_hoja
            progreso(f"  {p['nombre']}: hoja {n}")
            final, capas = productos.raster(p, jugadores, trabajo.equipo, aj, n, marca=trabajo.marca)
            nombre = productos.nombre_archivo(p, trabajo.equipo, n=n)
            hechos = [productos.guardar_raster(final, os.path.join(imp, nombre), fmt) for fmt in p["impresion"]]
            hechos.append(productos.guardar_psd(capas, tuple(p["lienzo"]), p["color"], os.path.join(edi, nombre),
                                                final))
            return hechos
        for hechos in hilos.map(hoja, list(enumerate(productos.hojas(p, jug), 1))):
            salidas += hechos
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

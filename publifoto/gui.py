"""Ventana del Programa Publifoto (PySide6)."""
import os
import sys
import traceback
from dataclasses import replace

import numpy as np
from PIL import Image, ImageDraw, ImageOps
from PySide6.QtCore import QObject, QSettings, Qt, QThread, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QImage, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMainWindow, QSizePolicy,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSlider,
                               QVBoxLayout, QWidget)

from . import actualizar, cartas, club, encuadre, motor, productos, revision, tema
from .tema import rol
from .analisis import abrir, girar

TIPOS = {"jugador": "Jugador", "entrenador": "Entrenador", "equipo": "Foto de equipo"}
_miniaturas = {}


def miniatura(ruta, lado=1200):
    if (ruta, lado) not in _miniaturas:
        # draft (decodificar el JPG ya reducido) tiene que ir antes de enderezar por EXIF
        im = Image.open(ruta)
        im.draft("RGB", (lado, lado))
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGBA" if ruta.lower().endswith(".png") else "RGB")
        im.thumbnail((lado, lado))
        _miniaturas[(ruta, lado)] = im
    return _miniaturas[(ruta, lado)]


def corta(ruta, partes=2):
    trozos = os.path.normpath(ruta).split(os.sep)
    return ("…" + os.sep if len(trozos) > partes else "") + os.sep.join(trozos[-partes:])


def a_pixmap(im):
    im = im.convert("RGBA")
    q = QImage(im.tobytes(), im.width, im.height, im.width * 4, QImage.Format_RGBA8888)
    return QPixmap.fromImage(q.copy())


def aspecto(p):
    if "calendarios" in p:
        r = p["calendarios"][0]["huecos"][0]["rect"]
    else:
        r = p["huecos"][0]["rect"]
    return (r[2] - r[0]) / (r[3] - r[1])


class Tarea(QObject):
    """Ejecuta una función larga fuera de la ventana."""
    mensaje = Signal(str)
    terminado = Signal(object)
    error = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def ejecutar(self):
        try:
            self.terminado.emit(self.fn(self.mensaje.emit))
        except Exception:
            self.error.emit(traceback.format_exc())


class SinRueda(QComboBox):
    """Desplegable que no cambia con la rueda del ratón al pasar por encima (al bajar por
    la lista de jugadores se cambiaba el tipo sin querer). Con clic sí."""

    def __init__(self, *a):
        super().__init__(*a)
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, e):
        if self.hasFocus() and self.view().isVisible():
            super().wheelEvent(e)
        else:
            e.ignore()


class ZonaArrastre(QLabel):
    soltada = Signal(str)

    def __init__(self, titulo, detalle):
        super().__init__()
        self.setAlignment(Qt.AlignCenter)
        self.setAcceptDrops(True)
        self.setMinimumHeight(104)
        self.setWordWrap(True)
        self.setCursor(Qt.PointingHandCursor)
        self.mostrar(titulo, detalle)
        self._estilo(False)

    def mostrar(self, titulo, detalle, hecho=False):
        if hecho:
            self.setToolTip(detalle)
            detalle = corta(detalle)
        marca = f"<span style='color:{tema.VERDE}'>✓</span> " if hecho else ""
        self.setText(f"<div style='font-size:16px;font-weight:700'>{marca}{titulo}</div>"
                     f"<div style='color:{tema.SUAVE};font-size:12px;margin-top:4px'>{detalle}</div>")

    def _estilo(self, activo):
        self.setStyleSheet(
            "QLabel{border:1.5px dashed %s;border-radius:16px;padding:14px;background:%s}"
            "QLabel:hover{border-color:#E6007F;background:#FFF4F9}"
            % (("#E6007F", "#FFE6F2") if activo else ("rgba(230,0,127,0.40)", "#FFFFFF")))

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._estilo(True)

    def dragLeaveEvent(self, e):
        self._estilo(False)

    def dropEvent(self, e):
        self._estilo(False)
        ruta = e.mimeData().urls()[0].toLocalFile()
        if os.path.isfile(ruta):
            ruta = os.path.dirname(ruta)
        self.soltada.emit(ruta)

    def mousePressEvent(self, e):
        ruta = QFileDialog.getExistingDirectory(self, "Elige la carpeta")
        if ruta:
            self.soltada.emit(ruta)


class Revision(QDialog):
    """Revisión rápida: el programa propone el encuadre y el operario lo corrige."""

    def __init__(self, trabajo, parent=None, producto=None, foto=None):
        super().__init__(parent)
        self.setWindowTitle("Revisión rápida de encuadres")
        self.resize(1000, 760)
        self.t = trabajo
        self._ir_a = foto
        lay = QHBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(16)
        izq = QVBoxLayout()
        self.producto = QComboBox()
        self.plantillas = [productos.cargar_plantilla(i) for i in trabajo.productos]
        for p in self.plantillas:
            self.producto.addItem(p["nombre"], p["id"])
        self.lista = QListWidget()
        izq.addWidget(tema.ceja("Producto"))
        izq.addWidget(self.producto)
        izq.addWidget(tema.ceja("Jugadores"))
        izq.addWidget(self.lista, 1)
        lay.addLayout(izq, 1)
        der = QVBoxLayout()
        self.vista = tema.Vista()
        self.vista.setMinimumSize(520, 620)
        der.addWidget(self.vista, 1)
        botones = QGridLayout()
        for txt, d, f, c in [("▲ Subir", (0, 0.01, 1), 0, 1), ("◀ Izquierda", (0.01, 0, 1), 1, 0),
                             ("Derecha ▶", (-0.01, 0, 1), 1, 2), ("▼ Bajar", (0, -0.01, 1), 2, 1),
                             ("+ Acercar", (0, 0, 1.03), 0, 3), ("− Alejar", (0, 0, 1 / 1.03), 2, 3)]:
            b = QPushButton(txt)
            b.setAutoRepeat(True)
            b.clicked.connect(lambda _=False, d=d: self.mover(*d))
            botones.addWidget(b, f, c)
        rest = QPushButton("Restablecer")
        rest.clicked.connect(self.restablecer)
        botones.addWidget(rest, 1, 1)
        for txt, g, c in [("↺ Girar 0,5°", 0.5, 4), ("↻ Girar 0,5°", -0.5, 4)]:
            b = QPushButton(txt)
            b.setAutoRepeat(True)
            b.clicked.connect(lambda _=False, g=g: self.girar(g))
            botones.addWidget(b, 0 if g > 0 else 2, c)
        self.lbl_giro = QLabel()
        self.lbl_giro.setAlignment(Qt.AlignCenter)
        botones.addWidget(self.lbl_giro, 1, 4)
        der.addLayout(botones)
        self.b_auto = QCheckBox("Enderezar la cabeza automáticamente en este primer plano")
        self.b_auto.toggled.connect(self.cambiar_auto)
        der.addWidget(self.b_auto)
        self.b_piel = QCheckBox("Quitar los granos y rojeces de esta foto")
        self.b_piel.toggled.connect(self.cambiar_piel)
        der.addWidget(self.b_piel)
        self.lbl_avisos = QLabel()
        self.lbl_avisos.setWordWrap(True)
        rol(self.lbl_avisos, "aviso")
        der.addWidget(self.lbl_avisos)
        nota = rol(QLabel("El giro manual endereza al jugador en todos los productos; el encuadre se recalcula "
                          "para que tenga las mismas medidas que los demás."), "suave")
        nota.setWordWrap(True)
        der.addWidget(nota)
        cerrar = rol(QPushButton("Listo"), "primario")
        cerrar.clicked.connect(self.accept)
        der.addWidget(cerrar)
        lay.addLayout(der, 2)
        self.producto.currentIndexChanged.connect(self.cambiar_producto)
        self.lista.currentRowChanged.connect(lambda _: self.pintar())
        if producto in trabajo.productos:
            self.producto.setCurrentIndex(trabajo.productos.index(producto))
        self.cambiar_producto()

    @property
    def plantilla(self):
        return self.plantillas[self.producto.currentIndex()]

    def avisos_de(self, j):
        return [a for a in self.t.avisos if a.foto == j.id and a.nivel != "corregido"
                and a.producto in (None, self.plantilla["id"])]

    def cambiar_producto(self):
        self.lista.clear()
        self.jug = motor.jugadores_para(self.t, self.plantilla)
        fila = 0
        for i, j in enumerate(self.jug):
            self.lista.addItem(("⚠ " if self.avisos_de(j) else "") + j.nombre)
            if j.id == self._ir_a:
                fila = i
        if self.jug:
            self.lista.setCurrentRow(fila)

    def cambiar_auto(self, si):
        j = self.actual()
        if j and j.sin_giro_auto == si:
            j.sin_giro_auto = not si
            if "inclinacion" not in j.revisados:
                j.revisados.append("inclinacion")
            self.pintar()

    def cambiar_piel(self, si):
        j = self.actual()
        if j and j.sin_retoque == si:
            j.sin_retoque = not si
            self.pintar()

    def ajuste(self, j):
        return self.t.ajustes.setdefault(self.plantilla["id"], {}).setdefault(j.id, {"dx": 0, "dy": 0, "zoom": 1})

    def mover(self, dx, dy, zoom):
        j = self.actual()
        if not j:
            return
        a = self.ajuste(j)
        a["dx"] += dx
        a["dy"] += dy
        a["zoom"] *= zoom
        self.pintar()

    def girar(self, grados):
        j = self.actual()
        if j:
            j.giro = round(j.giro + grados, 2)
            if "inclinacion" not in j.revisados:
                j.revisados.append("inclinacion")
            self.pintar()

    def restablecer(self):
        j = self.actual()
        if j:
            self.t.ajustes.get(self.plantilla["id"], {}).pop(j.id, None)
            j.giro = 0.0
            j.sin_giro_auto = False
            self.pintar()

    def actual(self):
        i = self.lista.currentRow()
        return self.jug[i] if 0 <= i < len(self.jug) else None

    def pintar(self):
        j = self.actual()
        if not j:
            self.vista.clear()
            self.b_auto.hide()
            self.b_piel.hide()
            self.lbl_giro.setText("")
            self.lbl_avisos.setText("No hay nadie en este producto." if not self.jug else "")
            return
        p = self.plantilla
        if p["id"] == "cartas":
            self.pintar_carta(j, p)
            return
        recorte = p.get("necesita_recorte") and j.ruta_recorte
        im = miniatura(j.ruta_recorte if recorte else j.ruta)
        f = im.width / j.puntos.ancho
        if self.t.retocar_piel and not j.sin_retoque and j.retoque:
            # lo que el retoque de piel va a quitar, marcado con un círculo
            im = im.copy()
            dib = ImageDraw.Draw(im)
            for x, y, r in j.retoque:
                R = max(6, r * im.width * 2.5)
                dib.ellipse((x * im.width - R, y * im.height - R, x * im.width + R, y * im.height + R),
                            outline=(230, 0, 127), width=2)
        enc = encuadre.Encuadre(**p["encuadre"])
        ar = aspecto(p)
        puntos, giro = productos.puntos_y_giro(j, p)
        im = girar(im, giro)
        self.lbl_giro.setText(f"Giro: {giro:+.1f}°".replace(".", ","))
        primer_plano = revision.es_primer_plano(p) and bool(j.giro_auto)
        self.b_auto.blockSignals(True)
        self.b_auto.setVisible(primer_plano)
        self.b_auto.setChecked(not j.sin_giro_auto)
        self.b_auto.setText(f"Enderezar la cabeza automáticamente en este primer plano ({j.giro_auto:+.1f}°)"
                            .replace(".", ","))
        self.b_auto.blockSignals(False)
        n = len(j.retoque)
        self.b_piel.blockSignals(True)
        self.b_piel.setVisible(bool(n) and self.t.retocar_piel)
        self.b_piel.setChecked(not j.sin_retoque)
        self.b_piel.setText(f"Quitar {'el grano o rojez' if n == 1 else f'los {n} granos o rojeces'} de esta foto")
        self.b_piel.blockSignals(False)
        self.lbl_avisos.setText("\n".join("⚠ " + a.texto for a in self.avisos_de(j)))
        caja = encuadre.calcular(puntos, ar, enc, self.t.ajustes.get(p["id"], {}).get(j.id))
        caja = encuadre.Caja(caja.x0 * f, caja.y0 * f, caja.x1 * f, caja.y1 * f)
        alto = 600
        vista = encuadre.recortar(im, caja, (int(alto * ar), alto))
        if vista.mode == "RGBA":
            fondo = Image.new("RGBA", vista.size, (243, 237, 241, 255))
            fondo.alpha_composite(vista)
            vista = fondo
        self.vista.setPixmap(a_pixmap(vista))

    def pintar_carta(self, j, p):
        """Cartas: el jugador recortado en la caja de la foto de la carta, como saldrá."""
        from . import carta_auto
        self.b_auto.hide()
        self.lbl_giro.setText("")
        n = len(j.retoque)
        self.b_piel.blockSignals(True)
        self.b_piel.setVisible(bool(n) and self.t.retocar_piel)
        self.b_piel.setChecked(not j.sin_retoque)
        self.b_piel.blockSignals(False)
        hecho = j.carta or carta_auto.en_cache(j)
        avisos = ["⚠ " + a.texto for a in self.avisos_de(j)]
        if not hecho:
            avisos.insert(0, "El recorte de la carta se hace al generar; después aquí se ve cómo "
                             "queda y se puede ajustar.")
            self.lbl_avisos.setText("\n".join(avisos))
            im = miniatura(j.ruta).copy()
            im.thumbnail((600, 600))
            self.vista.setPixmap(a_pixmap(im))
            return
        png, med = hecho
        self.lbl_avisos.setText("\n".join(avisos))
        im = miniatura(png)
        f = im.width / j.puntos.ancho
        col = p.get("colocacion", carta_auto.COLOCACION)
        # la colocación a la escala de la miniatura y de la vista (un cuarto de la carta)
        x0, y0, x1, y1 = col["caja"]
        red = 0.25
        col_v = dict(col, caja=[0, 0, int((x1 - x0) * red), int((y1 - y0) * red)],
                     centro=(col["centro"] - x0) * red, pelo=(col["pelo"] - y0) * red)
        med_v = dict(med, s=med["s"] * red / f, mid=med["mid"] * f, top=med["top"] * f)
        vista = carta_auto.colocar(im, med_v, col_v, self.t.ajustes.get(p["id"], {}).get(j.id))
        fondo = self._fondo_carta(p, col, red, vista.size)
        fondo.alpha_composite(vista)
        self.vista.setPixmap(a_pixmap(fondo))

    def _fondo_carta(self, p, col, red, tam):
        """La carta sin jugador (color, nombre y escudo del club), en el trozo de la foto."""
        clave = (self.t.carta, self.t.marca.get("escudo"), self.t.club, tam)
        if getattr(self, "_fondo_carta_clave", None) != clave:
            try:
                fondo, _ = cartas.fondo_club(p, self.t.carta, self.t.marca)
                x0, y0, x1, y1 = col["caja"]
                im = Image.fromarray(np.clip(fondo[y0:y1, x0:x1] + .5, 0, 255).astype(np.uint8))
                im = im.resize(tam, Image.LANCZOS).convert("RGBA")
            except Exception:
                im = Image.new("RGBA", tam, (243, 237, 241, 255))
            self._fondo_carta_clave, self._fondo_carta_im = clave, im
        return self._fondo_carta_im.copy()

    def keyPressEvent(self, e):
        teclas = {Qt.Key_Up: (0, 0.01, 1), Qt.Key_Down: (0, -0.01, 1), Qt.Key_Left: (0.01, 0, 1),
                  Qt.Key_Right: (-0.01, 0, 1), Qt.Key_Plus: (0, 0, 1.03), Qt.Key_Minus: (0, 0, 1 / 1.03)}
        if e.key() in (Qt.Key_BracketLeft, Qt.Key_BracketRight):
            self.girar(0.5 if e.key() == Qt.Key_BracketLeft else -0.5)
        elif e.key() in teclas:
            self.mover(*teclas[e.key()])
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e):
        self.mover(0, 0, 1.03 if e.angleDelta().y() > 0 else 1 / 1.03)


class EncuadrePlantilla(QDialog):
    """Encuadre predeterminado de un producto: cuánto ocupa el jugador en el hueco y
    dónde queda, probado con un jugador de ejemplo (uno del equipo cargado o una
    figura dibujada). Los ajustes de cada jugador en la revisión rápida van encima."""

    def __init__(self, id_, trabajo=None, marca=None, texto=None, parent=None):
        super().__init__(parent)
        self.p = productos.cargar_plantilla(id_)
        self.setWindowTitle(f"Encuadre de {self.p['nombre']}")
        self.resize(820, 760)
        self.enc = dict(self.p["encuadre"])
        self.inicial = dict(self.enc)
        self.ejemplos = self._ejemplos(trabajo)
        self.capas = self._capas(marca)
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        v.addWidget(tema.ceja(f"[ encuadre ]  {self.p['nombre']}"))
        if texto:
            t = QLabel(texto)
            t.setWordWrap(True)
            t.setStyleSheet(f"color:{tema.VERDE}")
            v.addWidget(t)
        v.addWidget(rol(QLabel("¿Cómo quieres que salga el jugador?"), "titulo"))
        sub = rol(QLabel("Lo que guardes aquí es como saldrán todos los jugadores de este producto a partir de "
                         "ahora."), "suave")
        sub.setWordWrap(True)
        v.addWidget(sub)
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Jugador de ejemplo:"))
        self.combo = QComboBox()
        for nombre, _, _ in self.ejemplos:
            self.combo.addItem(nombre)
        self.combo.currentIndexChanged.connect(lambda _: self.pintar())
        fila.addWidget(self.combo, 1)
        v.addLayout(fila)
        self.vista = tema.Vista()
        self.vista.setMinimumSize(480, 500)
        v.addWidget(self.vista, 1)
        botones = QGridLayout()
        for txt, accion, f, c in [("▲ Jugador más arriba", ("margen", -0.005), 0, 1),
                                  ("◀ A la izquierda", ("centro", 0.005), 1, 0),
                                  ("A la derecha ▶", ("centro", -0.005), 1, 2),
                                  ("▼ Jugador más abajo", ("margen", 0.005), 2, 1),
                                  ("+ Más cerca", ("alto_rel", 1 / 1.03), 0, 3),
                                  ("− Más lejos", ("alto_rel", 1.03), 2, 3)]:
            b = QPushButton(txt)
            b.setAutoRepeat(True)
            b.clicked.connect(lambda _=False, a=accion: self.mover(*a))
            botones.addWidget(b, f, c)
        antes = QPushButton("Como estaba")
        antes.clicked.connect(self.como_estaba)
        botones.addWidget(antes, 1, 1)
        v.addLayout(botones)
        self.lbl = rol(QLabel(), "suave")
        self.lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(self.lbl)
        fila = QHBoxLayout()
        fila.addStretch(1)
        cancelar = QPushButton("Dejarlo como estaba")
        cancelar.clicked.connect(self.reject)
        guardar = rol(QPushButton("Guardar como predeterminado"), "primario")
        guardar.setDefault(True)
        guardar.clicked.connect(self.guardar)
        fila.addWidget(cancelar)
        fila.addWidget(guardar)
        v.addLayout(fila)
        self.pintar()

    def _ejemplos(self, trabajo):
        """[(nombre, imagen, puntos)]: los jugadores del equipo cargado que salen en el
        producto y, siempre, una figura dibujada (sin fotos de nadie)."""
        from .comprobar import _figura
        ejemplos = []
        if trabajo and trabajo.jugadores:
            for j in motor.jugadores_para(trabajo, self.p):
                if j.puntos is None:
                    continue
                puntos, giro = productos.puntos_y_giro(j, self.p)
                im = miniatura(j.ruta)
                f = im.width / j.puntos.ancho
                puntos = replace(puntos, ancho=im.width, alto=round(puntos.alto * f))
                ejemplos.append((j.nombre, girar(im, giro), puntos))
        foto, _, puntos = _figura(0)
        ejemplos.append(("Figura dibujada", foto, puntos))
        return ejemplos

    def _capas(self, marca):
        """El escudo y lo que va encima de la foto (15x20 y pared), para verlo en su sitio."""
        capas = []
        if "lienzo" not in self.p:
            return capas
        if self.p["tipo"] == "carta":
            # logo, textos y separadores de la carta, encima del jugador
            return [(Image.open(os.path.join(self.p["_carpeta"], self.p["encima"])).convert("RGBA"), 0, 0)]
        from . import color
        for _, im, alfa, x, y in productos._encima(self.p, marca):
            if im.mode == "CMYK":
                im = color.cmyk_a_rgb(im).convert("RGBA")
                im.putalpha(alfa)
            capas.append((im.convert("RGBA"), x, y))
        return capas

    def mover(self, clave, valor):
        if clave == "alto_rel":
            self.enc[clave] = min(30.0, max(1.2, self.enc[clave] * valor))
        else:
            self.enc[clave] = min(0.5, max(-0.5 if clave == "centro" else 0.0, self.enc[clave] + valor))
        self.pintar()

    def como_estaba(self):
        self.enc = dict(self.inicial)
        self.pintar()

    def pintar(self):
        from PIL import ImageDraw
        _, im, puntos = self.ejemplos[self.combo.currentIndex()]
        ar = aspecto(self.p)
        alto = 520
        tam = (int(alto * ar), alto)
        caja = encuadre.calcular(puntos, ar, encuadre.Encuadre(**self.enc))
        vista = encuadre.recortar(im.convert("RGB"), caja, tam).convert("RGBA")
        hueco = self.p["calendarios"][0]["huecos"][0] if "calendarios" in self.p else self.p["huecos"][0]
        r = hueco["rect"]
        esc = tam[0] / (r[2] - r[0])
        for capa, x, y in self.capas:
            c = capa.resize((max(1, round(capa.width * esc)), max(1, round(capa.height * esc))), Image.LANCZOS)
            vista.alpha_composite(c, (round((x - r[0]) * esc), round((y - r[1]) * esc)))
        if "circulo" in hueco:
            # fuera del círculo del imán, oscurecido (es lo que se lleva el troquel)
            c = [(hueco["circulo"][i] - r[i % 2]) * esc for i in range(4)]
            mascara = Image.new("L", tam, 150)
            ImageDraw.Draw(mascara).ellipse(c, fill=0)
            negro = Image.new("L", tam, 0)
            vista.alpha_composite(Image.merge("RGBA", (negro, negro, negro, mascara)))
            ImageDraw.Draw(vista).ellipse(c, outline=(255, 255, 255, 255), width=2)
        self.vista.setPixmap(a_pixmap(vista))
        cambiado = "" if self.enc == self.inicial else "  (cambiado)"
        self.lbl.setText(f"Espacio encima de la cabeza: {self.enc['margen'] * 100:.1f} % · "
                         f"el hueco mide {self.enc['alto_rel']:.2f} cabezas de alto{cambiado}".replace(".", ","))

    def guardar(self):
        if self.enc != self.inicial:
            actualizar.guardar_encuadre(self.p["id"], self.enc)
        self.accept()

    def keyPressEvent(self, e):
        teclas = {Qt.Key_Up: ("margen", -0.005), Qt.Key_Down: ("margen", 0.005),
                  Qt.Key_Left: ("centro", 0.005), Qt.Key_Right: ("centro", -0.005),
                  Qt.Key_Plus: ("alto_rel", 1 / 1.03), Qt.Key_Minus: ("alto_rel", 1.03)}
        if e.key() in teclas:
            self.mover(*teclas[e.key()])
        else:
            super().keyPressEvent(e)

    def wheelEvent(self, e):
        self.mover("alto_rel", 1 / 1.03 if e.angleDelta().y() > 0 else 1.03)


class Ventana(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Publifoto")
        self.resize(1240, 880)
        self.setMinimumSize(1020, 720)
        self.ajustes_app = QSettings("Publifoto", "Programa")
        self.trabajo = None
        self.hilo = None
        self.desde_proyecto = False
        central = tema.Fondo()
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(28, 18, 28, 18)
        lay.setSpacing(14)

        # cabecera: nombre, qué es y si está trabajando
        cab = QHBoxLayout()
        cab.addWidget(tema.logo())
        cab.addSpacing(16)
        cab.addWidget(tema.ceja("[ fútbol ]  fotos de equipo a productos"), 0, Qt.AlignVCenter)
        cab.addStretch()
        b_abrir = rol(QPushButton("Abrir proyecto…"), "enlace")
        b_abrir.clicked.connect(self.abrir_proyecto)
        b_plantillas = QPushButton("Plantillas…")
        b_plantillas.setToolTip("Actualizar una plantilla con el archivo de un año nuevo o cambiar su encuadre")
        b_plantillas.clicked.connect(self.dialogo_plantillas)
        self.pastilla = rol(QLabel(), "estado")
        for w in (b_abrir, b_plantillas, self.pastilla):
            cab.addWidget(w, 0, Qt.AlignVCenter)
        lay.addLayout(cab)

        # 01 fotos y 02 club
        fila = QHBoxLayout()
        fila.setSpacing(14)
        t1, v1 = tema.tarjeta("Fotos del equipo", 1)
        zonas = QHBoxLayout()
        zonas.setSpacing(12)
        self.zona = ZonaArrastre("Carpeta ARREGLADAS", "Arrástrala aquí o haz clic para elegirla")
        self.zona.soltada.connect(self.cargar_fotos)
        self.zona_rec = ZonaArrastre("Carpeta RECORTADAS (opcional)",
                                     "Las cartas se recortan solas · si tienes PNG sin fondo, arrástralos aquí")
        self.zona_rec.soltada.connect(self.cargar_recortes)
        zonas.addWidget(self.zona, 3)
        zonas.addWidget(self.zona_rec, 2)
        v1.addLayout(zonas)
        self.info = rol(QLabel("Todavía no hay ningún equipo cargado."), "suave")
        v1.addWidget(self.info)
        fila.addWidget(t1, 3)

        # escudo y nombre del club: cambian en 15 x 20, calendarios, imanes y cartas; el
        # color de las cartas se elige solo con el escudo (y se puede cambiar)
        t2, v2 = tema.tarjeta("Club", 2)
        f_escudo = QHBoxLayout()
        self.vista_escudo = QLabel()
        self.vista_escudo.setFixedSize(52, 52)
        self.vista_escudo.setAlignment(Qt.AlignCenter)
        self.vista_escudo.setStyleSheet(f"background:#FFFFFF;border:1px solid {tema.BORDE};"
                                        "border-radius:14px")
        self.combo_escudo = QComboBox()
        self.combo_escudo.setMinimumWidth(200)
        b_logos = rol(QPushButton("+ Añadir logos"), "enlace")
        b_logos.setToolTip("Elige una carpeta con los escudos de los clubs: el nombre de cada archivo es el del club.")
        b_logos.clicked.connect(self.anadir_logos)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(self.combo_escudo)
        col.addWidget(b_logos, 0, Qt.AlignLeft)
        f_escudo.addWidget(self.vista_escudo, 0, Qt.AlignTop)
        f_escudo.addLayout(col, 1)
        v2.addLayout(f_escudo)
        self.txt_club = QLineEdit()
        self.txt_club.setPlaceholderText("C.F. AMPOSTA")
        self.txt_club.setToolTip("Nombre del club en la franja de los imanes (las cartas llevan el de su plantilla)")
        self.txt_temporada = QLineEdit(club.temporada_actual())
        self.txt_temporada.setFixedWidth(76)
        self.combo_carta = SinRueda()
        self.combo_carta.setToolTip("La plantilla de carta de cada equipo, con su color, su escudo y su nombre "
                                    "ya puestos. Se elige sola con el escudo del club y se puede cambiar aquí.")
        self.plantilla_cartas = productos.cargar_plantilla("cartas")
        for clave, nombre in cartas.colores(self.plantilla_cartas):
            club_carta = cartas.nombre_club(self.plantilla_cartas, clave) or ("C.F. AMPOSTA" if not clave else "")
            self.combo_carta.addItem(f"{nombre}  ·  {club_carta}" if club_carta else nombre, clave or "")
        f_texto = QGridLayout()
        f_texto.setHorizontalSpacing(10)
        f_texto.setVerticalSpacing(4)
        f_texto.addWidget(rol(QLabel("Nombre del club (imanes)"), "suave"), 0, 0)
        f_texto.addWidget(rol(QLabel("Temporada"), "suave"), 0, 1)
        f_texto.addWidget(self.txt_club, 1, 0)
        f_texto.addWidget(self.txt_temporada, 1, 1)
        f_texto.addWidget(rol(QLabel("Plantilla de carta del equipo"), "suave"), 2, 0)
        f_texto.addWidget(self.combo_carta, 3, 0, 1, 2)
        v2.addLayout(f_texto)
        fila.addWidget(t2, 2)
        lay.addLayout(fila)
        self.pintar_logos(self.ajustes_app.value("escudo", ""))
        self._poner_carta(self._carta_de_escudo())
        self.combo_escudo.currentIndexChanged.connect(self.escudo_cambiado)
        self.combo_carta.currentIndexChanged.connect(self.carta_cambiada)

        # 03 productos
        t3, v3 = tema.tarjeta("¿Qué quieres hacer?", 3)
        prod = QHBoxLayout()
        prod.setSpacing(8)
        self.casillas = {}
        for p in productos.lista_plantillas():
            c = rol(QCheckBox(p["nombre"].capitalize()), "pastilla")
            c.setCursor(Qt.PointingHandCursor)
            c.setChecked(True)
            c.toggled.connect(self.productos_cambiados)
            self.casillas[p["id"]] = c
            prod.addWidget(c)
        prod.addStretch()
        v3.addLayout(prod)
        self.b_piel = QCheckBox("Retocar la piel: quitar granos y rojeces que se noten (las pecas y los lunares se dejan)")
        self.b_piel.setChecked(True)
        self.b_piel.toggled.connect(self.piel_cambiada)
        v3.addWidget(self.b_piel)
        lay.addWidget(t3)

        # 04 jugadores y revisión automática
        t4, v4 = tema.tarjeta("Jugadores", 4)
        self.rejilla = QWidget()
        self.rejilla_lay = QGridLayout(self.rejilla)
        self.rejilla_lay.setSpacing(12)
        self.rejilla_lay.setContentsMargins(0, 0, 0, 0)
        self.rejilla_lay.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        sc = QScrollArea()
        sc.setWidgetResizable(True)
        sc.setWidget(self.rejilla)
        v4.addWidget(sc, 1)
        self.lbl_rev = QLabel("")
        v4.addWidget(self.lbl_rev)
        self.lista_avisos = QListWidget()
        self.lista_avisos.setMaximumHeight(120)
        self.lista_avisos.itemDoubleClicked.connect(self.abrir_aviso)
        self.lista_avisos.hide()
        v4.addWidget(self.lista_avisos)
        lay.addWidget(t4, 1)

        # abajo: dónde se guarda, cómo va y los botones
        abajo = QHBoxLayout()
        abajo.setSpacing(10)
        self.lbl_salida = rol(QLabel(), "suave")
        b = rol(QPushButton("Cambiar"), "enlace")
        b.clicked.connect(self.elegir_salida)
        self.b_registro = rol(QPushButton("Registro"), "enlace")
        self.b_registro.setCheckable(True)
        self.estado = rol(QLabel(""), "suave")
        self.barra = QProgressBar()
        self.barra.setRange(0, 0)
        self.barra.setTextVisible(False)
        self.barra.setFixedWidth(160)
        self.barra.hide()
        self.b_revisar = QPushButton("Revisión rápida de encuadres")
        self.b_revisar.clicked.connect(self.revisar)
        self.b_generar = rol(QPushButton("Generar  →"), "primario")
        self.b_generar.clicked.connect(self.generar)
        for w in (self.lbl_salida, b, self.b_registro):
            abajo.addWidget(w)
        abajo.addStretch(1)
        for w in (self.estado, self.barra, self.b_revisar, self.b_generar):
            abajo.addWidget(w)
        lay.addLayout(abajo)
        self.registro = QPlainTextEdit()
        self.registro.setReadOnly(True)
        self.registro.setMaximumHeight(110)
        self.registro.hide()
        self.b_registro.toggled.connect(self.registro.setVisible)
        lay.addWidget(self.registro)
        self.activar(False)
        self.actualizar_salida()

    # --- escudo del club y plantillas ---------------------------------------
    def pintar_logos(self, elegido=None):
        self.combo_escudo.blockSignals(True)
        self.combo_escudo.clear()
        self.combo_escudo.addItem("El de la plantilla (C.F. AMPOSTA)", None)
        for nombre, ruta in club.lista_logos():
            self.combo_escudo.addItem(nombre, ruta)
        i = self.combo_escudo.findData(elegido) if elegido else 0
        self.combo_escudo.setCurrentIndex(max(0, i))
        self.combo_escudo.blockSignals(False)
        self._pintar_escudo()

    def _pintar_escudo(self):
        ruta = self.combo_escudo.currentData()
        if ruta and os.path.exists(ruta):
            self.vista_escudo.setPixmap(a_pixmap(club.ajustado(ruta, (88, 88))).scaled(
                44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            ruta = os.path.join(productos.PLANTILLAS, "15x20", "logo.png")
            self.vista_escudo.setPixmap(a_pixmap(club.ajustado(ruta, (88, 88))).scaled(
                40, 40, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def escudo_cambiado(self):
        ruta = self.combo_escudo.currentData()
        self.ajustes_app.setValue("escudo", ruta or "")
        self._poner_carta(self._carta_de_escudo())
        nombre = self.combo_escudo.currentText()
        if not ruta:
            texto = ""
        elif club.texto_guardado(nombre) and not (cartas.con_plantilla(self.plantilla_cartas, nombre) and
                                                   club.texto_guardado(nombre) == nombre.upper()):
            # (el nombre del archivo guardado sin escribirlo no vale: va el del equipo)
            texto = club.texto_guardado(nombre)
        elif cartas.con_plantilla(self.plantilla_cartas, nombre):
            texto = cartas.nombre_club(self.plantilla_cartas, self.combo_carta.currentData() or None)
        else:
            texto = club.texto_club(nombre)
        self.txt_club.setText(texto)
        self._pintar_escudo()

    def _carta_de_escudo(self):
        """Color de carta para el escudo elegido: el que se eligió la última vez para ese
        escudo o, si no, el del club que nombra (Tortosa, Batea...)."""
        if not self.combo_escudo.currentData():
            return ""
        nombre = self.combo_escudo.currentText()
        # el escudo de un equipo con plantilla propia lleva siempre la suya
        if cartas.con_plantilla(self.plantilla_cartas, nombre):
            return cartas.color_para(self.plantilla_cartas, nombre) or ""
        # un club sin plantilla: la que se eligió la última vez para él
        return self.ajustes_app.value("carta/" + nombre, "") or ""

    def _poner_carta(self, clave):
        self.combo_carta.blockSignals(True)
        self.combo_carta.setCurrentIndex(max(0, self.combo_carta.findData(clave or "")))
        self.combo_carta.blockSignals(False)
        self.txt_club.setPlaceholderText(cartas.nombre_club(self.plantilla_cartas, clave or None) or "C.F. AMPOSTA")

    def carta_cambiada(self):
        """Se elige la plantilla de un equipo: su nombre pasa al nombre del club (salvo uno
        escrito a mano). El escudo no se toca: se puede usar cualquier escudo con cualquier
        plantilla y escribir el nombre que se quiera."""
        p = self.plantilla_cartas
        clave = self.combo_carta.currentData() or None
        if self.combo_escudo.currentData():
            self.ajustes_app.setValue("carta/" + self.combo_escudo.currentText(), clave or "")
        de_plantillas = {cartas.nombre_club(p, c) or "C.F. AMPOSTA" for c, _ in cartas.colores(p)}
        escudo = self.combo_escudo.currentText() if self.combo_escudo.currentData() else ""
        escrito = self.txt_club.text().strip()
        if not escrito or escrito in de_plantillas or escrito == club.texto_club(escudo):
            self.txt_club.setText(cartas.nombre_club(p, clave) or "C.F. AMPOSTA")
        self._poner_carta(clave)

    def anadir_logos(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Carpeta con los escudos de los clubs")
        if not carpeta:
            return
        nuevos = club.importar_logos(carpeta)
        self.pintar_logos(self.combo_escudo.currentData())
        QMessageBox.information(self, "Logos", f"Se han añadido {len(nuevos)} escudos." if nuevos else
                                "En esa carpeta no hay imágenes de escudos (PNG, TIF o JPG).")

    def marca_a_trabajo(self, t):
        """Lo elegido en la ventana pasa al trabajo; el nombre del club se recuerda para ese escudo."""
        t.escudo = self.combo_escudo.currentData()
        t.club = self.txt_club.text().strip() or None
        t.carta = self.combo_carta.currentData() or None
        t.temporada = self.txt_temporada.text().strip() or None
        if t.escudo and t.club:
            club.guardar_texto_club(self.combo_escudo.currentText(), t.club)

    def marca_de_trabajo(self, t):
        if t.escudo and self.combo_escudo.findData(t.escudo) < 0 and os.path.exists(t.escudo):
            self.combo_escudo.addItem(os.path.splitext(os.path.basename(t.escudo))[0], t.escudo)
        self.combo_escudo.blockSignals(True)
        self.combo_escudo.setCurrentIndex(max(0, self.combo_escudo.findData(t.escudo)) if t.escudo else 0)
        self.combo_escudo.blockSignals(False)
        self._pintar_escudo()
        self._poner_carta(t.carta)
        self.txt_club.setText(t.club or "")
        self.txt_temporada.setText(t.temporada or club.temporada_actual())

    def dialogo_plantillas(self):
        d = QDialog(self)
        d.setWindowTitle("Plantillas")
        d.setMinimumWidth(760)
        v = QVBoxLayout(d)
        v.setContentsMargins(24, 20, 24, 20)
        v.setSpacing(12)
        v.addWidget(tema.ceja("[ plantillas ]  de cada año"))
        v.addWidget(rol(QLabel("Plantillas"), "titulo"))
        v.addWidget(rol(QLabel("Para poner la plantilla de un año nuevo, elige su archivo original.\n"
                           "El programa la convierte, la prueba y, si sale bien, la usa a partir de ahora.\n"
                           "«Encuadre…» cambia cómo sale el jugador (más cerca, más lejos, más arriba...)."), "suave"))
        elegido = {}
        filas = list(actualizar.ACTUALIZABLES.items()) + [("llaveros", ("Llaveros", None, ""))]
        for id_, (nombre, filtro, ayuda) in filas:
            fila = QHBoxLayout()
            etiqueta = QLabel(f"<b>{nombre}</b><br><span style='color:{tema.SUAVE};font-size:12px'>"
                              f"{actualizar.info(id_)}</span>")
            etiqueta.setToolTip(ayuda)
            b = rol(QPushButton("Actualizar…"), "blanco")
            b.setToolTip(ayuda)
            b.setVisible(filtro is not None)
            e = QPushButton("Encuadre…")
            o = rol(QPushButton("Volver a la original"), "enlace")
            o.setEnabled(actualizar.propia(id_))

            def encuadrar(_=False, id_=id_):
                if self.dialogo_encuadre(id_):
                    d.reject()
                    self.dialogo_plantillas()

            def pedir(_=False, id_=id_, filtro=filtro, nombre=nombre):
                ruta, _f = QFileDialog.getOpenFileName(d, f"Archivo nuevo: {nombre}", "", filtro)
                if ruta:
                    elegido.update(id_=id_, ruta=ruta)
                    d.accept()

            def original(_=False, id_=id_, nombre=nombre):
                if QMessageBox.question(d, "Volver a la original",
                                        f"¿Usar otra vez la plantilla de {nombre} que viene con el programa?") \
                        == QMessageBox.Yes:
                    actualizar.restaurar(id_)
                    d.reject()
                    self.dialogo_plantillas()

            b.clicked.connect(pedir)
            e.clicked.connect(encuadrar)
            o.clicked.connect(original)
            fila.addWidget(etiqueta, 1)
            fila.addWidget(o)
            fila.addWidget(e)
            fila.addWidget(b)
            v.addLayout(fila)
        cerrar = QPushButton("Cerrar")
        cerrar.clicked.connect(d.reject)
        v.addWidget(cerrar, 0, Qt.AlignRight)
        if d.exec() == QDialog.Accepted and elegido:
            self.en_segundo_plano(lambda prog: actualizar.actualizar(elegido["id_"], elegido["ruta"], prog),
                                  self.plantilla_actualizada)

    def plantilla_actualizada(self, r):
        # al subir una plantilla se pregunta enseguida cómo tiene que salir el jugador
        self.dialogo_encuadre(r["id"], "✓ La plantilla nueva funciona y se usa a partir de ahora: " + r["resumen"] +
                              ("<br>⚠ " + "<br>".join(r["avisos"]) if r["avisos"] else ""))

    def dialogo_encuadre(self, id_, texto=None):
        """Devuelve True si se ha guardado un encuadre nuevo."""
        marca = {"escudo": self.combo_escudo.currentData()}
        d = EncuadrePlantilla(id_, self.trabajo, marca, texto, self)
        if d.exec() != QDialog.Accepted:
            return False
        self.productos_cambiados()   # los avisos de encuadre se rehacen con el nuevo
        return True

    # --- carga -------------------------------------------------------------
    def activar(self, si):
        self.b_generar.setEnabled(si)
        self.b_revisar.setEnabled(si)
        # mientras trabaja en segundo plano no se puede tocar nada que el motor esté leyendo
        ocupado = self.hilo is not None and self.hilo.isRunning()
        self.pastilla.setText(tema.punto(tema.ROSA) + "  TRABAJANDO" if ocupado else tema.punto(tema.VERDE) + "  LISTO")
        for w in (self.rejilla, self.lista_avisos, self.zona, self.zona_rec, *self.casillas.values(),
                  self.combo_escudo, self.txt_club, self.txt_temporada):
            w.setEnabled(not ocupado)

    def ocupado(self):
        return self.hilo is not None and self.hilo.isRunning()

    def piel_cambiada(self, si):
        if self.trabajo:
            self.trabajo.retocar_piel = si

    def productos_cambiados(self):
        if self.trabajo and self.trabajo.jugadores and not self.ocupado():
            self.trabajo.productos = self.productos_elegidos()
            motor.revisar_encuadres(self.trabajo)
            self.pintar_avisos()

    def actualizar_salida(self):
        s = self.carpeta_salida()
        self.lbl_salida.setText(f"Resultados en  <span style='color:{tema.TEXTO}'>"
                                f"{corta(s) if s else 'la carpeta que arrastres'}</span>")
        self.lbl_salida.setToolTip(s or "")

    def carpeta_salida(self):
        if self.trabajo:
            return self.trabajo.carpeta_equipo
        return ""

    def elegir_salida(self):
        """Otra carpeta solo para este equipo: los productos van en <carpeta>/<equipo>.
        No se recuerda: el siguiente equipo vuelve a ir en la carpeta que se arrastre."""
        if not self.trabajo:
            QMessageBox.information(self, "Carpeta de resultados",
                                    "Los resultados se guardan en la carpeta de fotos que arrastres. "
                                    "Arrastra primero las fotos y luego podrás cambiarla para ese equipo.")
            return
        r = QFileDialog.getExistingDirectory(self, "Carpeta donde guardar los resultados")
        if r:
            self.trabajo.carpeta_salida, self.trabajo.subcarpeta = r, True
            self.actualizar_salida()

    def cargar_fotos(self, carpeta):
        if not motor.buscar_fotos(carpeta):
            QMessageBox.warning(self, "Sin fotos", "En esa carpeta no hay fotos.")
            return
        propuesto = os.path.basename(carpeta.rstrip("/\\"))
        if propuesto.upper() in ("ARREGLADES", "ARREGLADAS"):
            propuesto = os.path.basename(os.path.dirname(carpeta.rstrip("/\\")))
        equipo, ok = QInputDialog.getText(self, "Nombre del equipo", "¿Cómo se llama el equipo?", text=propuesto)
        if not ok or not equipo.strip():
            return
        # los productos van dentro de la misma carpeta que se ha arrastrado
        self.trabajo = motor.Trabajo(equipo=equipo.strip(), carpeta_fotos=carpeta, carpeta_salida=carpeta,
                                     subcarpeta=False, retocar_piel=self.b_piel.isChecked())
        self.desde_proyecto = False
        if self.zona_rec.property("ruta"):
            self.trabajo.carpeta_recortes = self.zona_rec.property("ruta")
        self.zona.mostrar(equipo.strip(), carpeta, hecho=True)
        self.analizar()

    def cargar_recortes(self, carpeta):
        self.zona_rec.setProperty("ruta", carpeta)
        self.zona_rec.mostrar("Recortadas", carpeta, hecho=True)
        if self.trabajo:
            self.trabajo.carpeta_recortes = carpeta
            self.analizar()

    def abrir_proyecto(self):
        ruta, _ = QFileDialog.getOpenFileName(self, "Abrir proyecto", "", "Proyecto Publifoto (*.publifoto)")
        if not ruta:
            return
        self.en_segundo_plano(lambda prog: motor.abrir_proyecto(ruta, prog), self._proyecto_abierto)

    def _proyecto_abierto(self, t):
        self.trabajo = t
        self.desde_proyecto = True
        self.marca_de_trabajo(t)
        self.zona.mostrar(t.equipo, t.carpeta_fotos, hecho=True)
        for id_, c in self.casillas.items():
            c.setChecked(id_ in t.productos)
        self.b_piel.setChecked(t.retocar_piel)
        self.analizado(t)

    def analizar(self):
        t = self.trabajo
        self.en_segundo_plano(lambda prog: motor.preparar(t, prog), self.analizado)

    def analizado(self, t):
        self.actualizar_salida()
        t.productos = self.productos_elegidos()
        motor.revisar_encuadres(t)
        self.pintar_fotos()
        self.pintar_info()
        self.pintar_avisos()
        self.activar(True)

    def pintar_avisos(self):
        """Resumen de los revisores automáticos: solo se listan las cosas que hay que mirar."""
        t = self.trabajo
        nombres = {p["id"]: p["nombre"] for p in productos.lista_plantillas()}
        fuera = {j.id for j in t.jugadores if not j.incluido}
        # de los que no se van a imprimir solo interesa por qué se han quedado fuera
        avisos = [a for a in t.avisos if a.foto not in fuera or a.nivel == "error"]
        corregidos = [a for a in avisos if a.nivel == "corregido"]
        mirar = [a for a in avisos if a.nivel != "corregido"]
        self.lista_avisos.clear()
        for a in sorted(mirar, key=lambda a: (a.nivel != "error", a.foto)):
            donde = f" [{nombres.get(a.producto, a.producto)}]" if a.producto else ""
            it = QListWidgetItem(("⛔ " if a.nivel == "error" else "⚠ ") + f"{a.foto}{donde}: {a.texto}")
            it.setData(Qt.UserRole, a)
            it.setToolTip("Doble clic para verlo")
            self.lista_avisos.addItem(it)
        self.lista_avisos.setVisible(bool(mirar))
        texto = f"<b>Revisión automática:</b> {len(corregidos)} correcciones hechas solas"
        texto += (f", <span style='color:{tema.AMBAR}'><b>{len(mirar)} cosas para mirar</b></span> "
                  "(doble clic para verlas)." if mirar
                  else f", <span style='color:{tema.VERDE}'><b>todo correcto</b></span>.")
        self.lbl_rev.setText(texto)
        self.lbl_rev.setToolTip("\n".join(f"{a.foto}: {a.texto}" for a in corregidos))

    def abrir_aviso(self, item):
        a = item.data(Qt.UserRole)
        if self.ocupado():
            return
        if a.revisor == "presencia":
            QMessageBox.warning(self, "Falta una persona", f"{a.foto}: {a.texto}")
            return
        if a.revisor == "salida":
            QMessageBox.warning(self, "Archivos generados", f"{a.foto} {a.texto}".strip())
            if os.path.isdir(self.trabajo.carpeta_equipo):
                QDesktopServices.openUrl(QUrl.fromLocalFile(self.trabajo.carpeta_equipo))
            return
        if a.revisor == "clasificacion":
            QMessageBox.information(self, "Clasificación", f"{a.foto}: {a.texto}\n\n"
                                    "Elige el tipo correcto en su casilla de la lista de fotos.")
            return
        j = next((j for j in self.trabajo.jugadores if j.id == a.foto), None)
        if j is not None and not j.incluido:
            QMessageBox.information(self, "Foto fuera", f"{a.foto}: {a.texto}")
            return
        self.trabajo.productos = self.productos_elegidos()
        if not self.trabajo.productos:
            QMessageBox.information(self, "Sin productos", "Marca al menos un producto para ver el encuadre.")
            return
        prod = a.producto if a.producto in self.trabajo.productos else None
        if prod is None:
            # el primer producto donde sale esa persona (los primeros planos primero)
            for p in sorted((productos.cargar_plantilla(i) for i in self.trabajo.productos),
                            key=lambda p: not revision.es_primer_plano(p)):
                if any(j.id == a.foto for j in motor.jugadores_para(self.trabajo, p)):
                    prod = p["id"]
                    break
        if prod:
            self.marca_a_trabajo(self.trabajo)
            Revision(self.trabajo, self, prod, a.foto).exec()
            self.tras_revision(a)
        else:
            QMessageBox.information(self, "Aviso", f"{a.foto}: {a.texto}\n\n"
                                    "No sale en ninguno de los productos marcados.")

    def tras_revision(self, visto=None):
        """Tras la revisión manual: el operario ya ha mirado lo avisado; se vuelven a pasar
        los revisores de encuadre."""
        t = self.trabajo
        if visto is not None and visto.nivel == "revisar":
            # el operario ya lo ha mirado: no vuelve a salir (tampoco al reabrir el proyecto)
            j = next((j for j in t.jugadores if j.id == visto.foto), None)
            if j is not None and visto.revisor not in j.revisados:
                j.revisados.append(visto.revisor)
        t.productos = self.productos_elegidos()
        motor.revisar_encuadres(t)
        self.pintar_fotos()
        self.pintar_info()
        self.pintar_avisos()

    def pintar_info(self):
        t = self.trabajo
        n = {k: sum(1 for j in t.jugadores if j.tipo == k) for k in TIPOS}
        self.info.setText(f"<span style='color:{tema.TEXTO};font-weight:700'>{t.equipo}</span>  ·  "
                          f"{n['jugador']} jugadores  ·  {n['entrenador']} entrenadores  ·  "
                          f"{n['equipo']} foto de equipo")

    def cambiar_tipo(self, j, combo):
        j.tipo = combo.currentData()
        j.tipo_manual = True
        combo.setProperty("duda", False)
        tema.repintar(combo)
        self.trabajo.avisos = [a for a in self.trabajo.avisos
                               if not (a.foto == j.id and a.revisor == "clasificacion")]
        self.tras_revision()

    def pintar_fotos(self):
        while self.rejilla_lay.count():
            w = self.rejilla_lay.takeAt(0).widget()
            if w:
                w.deleteLater()
        for i, j in enumerate(self.trabajo.jugadores):
            caja = QFrame()
            caja.setObjectName("jugador")
            caja.setFixedWidth(150)
            caja.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            v = QVBoxLayout(caja)
            v.setContentsMargins(10, 10, 10, 10)
            v.setSpacing(6)
            img = QLabel()
            mini = miniatura(j.ruta, 400).copy()
            mini.thumbnail((128, 150))
            img.setPixmap(a_pixmap(mini))
            img.setAlignment(Qt.AlignCenter)
            img.setFixedHeight(150)
            v.addWidget(img)
            cb = QCheckBox(j.nombre)
            cb.setChecked(j.incluido)
            cb.toggled.connect(lambda s, j=j: (setattr(j, "incluido", s), self.pintar_avisos()))
            v.addWidget(cb)
            tipo = SinRueda()
            for k, txt in TIPOS.items():
                tipo.addItem(txt, k)
            tipo.setCurrentIndex(list(TIPOS).index(j.tipo))
            if not j.tipo_seguro and not j.tipo_manual:
                tipo.setProperty("duda", True)
                tipo.setToolTip("No está claro: compruébalo")
            tipo.currentIndexChanged.connect(lambda _, j=j, w=tipo: self.cambiar_tipo(j, w))
            v.addWidget(tipo)
            if j.giro_auto and not j.sin_giro_auto:
                v.addWidget(rol(QLabel(f"↻ llavero {j.giro_auto:+.1f}°".replace(".", ",")), "suave"))
            if j.ruta_recorte:
                v.addWidget(rol(QLabel("✓ recorte"), "suave"))
            self.rejilla_lay.addWidget(caja, i // 7, i % 7)

    # --- revisión y generación ---------------------------------------------
    def productos_elegidos(self):
        return [k for k, c in self.casillas.items() if c.isChecked()]

    def revisar(self):
        self.trabajo.productos = self.productos_elegidos()
        if not self.trabajo.productos:
            return
        self.marca_a_trabajo(self.trabajo)
        Revision(self.trabajo, self).exec()
        self.tras_revision()

    def generar(self):
        t = self.trabajo
        t.productos = self.productos_elegidos()
        self.marca_a_trabajo(t)
        if not t.productos:
            QMessageBox.information(self, "Nada que hacer", "Marca al menos un producto.")
            return
        avisos = motor.comprobar(t)
        motor.revisar_encuadres(t)
        self.pintar_avisos()
        errores = [a for a in t.avisos if a.nivel == "error"]
        faltan = [a for a in errores if a.revisor == "presencia"]
        if faltan:
            avisos.append(f"⛔ {len(faltan)} personas no saldrían bien en algún producto (⛔ en la lista).")
        if len(errores) > len(faltan):
            avisos.append(f"Los revisores han encontrado {len(errores) - len(faltan)} fallos de encuadre (⛔ en la lista).")
        if avisos and QMessageBox.question(self, "Antes de generar", "\n".join(avisos) + "\n\n¿Seguir igualmente?") \
                != QMessageBox.Yes:
            return
        hechos = [p["nombre"] for p in map(productos.cargar_plantilla, t.productos)
                  if os.path.exists(os.path.join(t.carpeta_equipo, p["nombre"]))]
        if hechos and not self.desde_proyecto:
            caja = QMessageBox(self)
            caja.setWindowTitle("Ya hay resultados")
            caja.setText(f"En «{corta(t.carpeta_equipo)}» ya están: {', '.join(hechos)}.")
            sob = caja.addButton("Sobrescribir", QMessageBox.AcceptRole)
            nueva = caja.addButton("Crear versión nueva", QMessageBox.ActionRole)
            caja.addButton("Cancelar", QMessageBox.RejectRole)
            caja.exec()
            if caja.clickedButton() == nueva:
                n = 2
                base = t.carpeta_equipo
                while os.path.exists(os.path.join(base, f"{t.equipo} ({n})")):
                    n += 1
                # la versión nueva va en una carpeta aparte dentro de la de resultados
                t.carpeta_salida, t.subcarpeta, t.equipo = base, True, f"{t.equipo} ({n})"
            elif caja.clickedButton() != sob:
                return
        self.en_segundo_plano(lambda prog: motor.generar(t, prog), self.generado)

    def generado(self, salidas):
        self.registro.appendPlainText(f"Listo: {len(salidas)} archivos.")
        self.pintar_avisos()
        fallos = [a for a in self.trabajo.avisos if a.revisor == "salida"]
        comprobado = ("⛔ La revisión de los archivos ha encontrado fallos:\n" +
                      "\n".join(f"  {a.foto} {a.texto}" for a in fallos[:10]) if fallos
                      else "✓ Revisados: están todos los archivos y todas las personas.")
        r = QMessageBox.question(self, "Terminado", f"Se han creado {len(salidas)} archivos en\n"
                                 f"{self.trabajo.carpeta_equipo}\n\n{comprobado}\n\n¿Abrir la carpeta?")
        if r == QMessageBox.Yes:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.trabajo.carpeta_equipo))

    def en_segundo_plano(self, fn, al_terminar):
        self.activar(False)
        self.barra.show()
        self._al_terminar = al_terminar
        self.hilo = QThread()
        self.tarea = Tarea(fn)
        self.tarea.moveToThread(self.hilo)
        self.hilo.started.connect(self.tarea.ejecutar)
        # métodos de la ventana: Qt los ejecuta en el hilo de la ventana
        self.tarea.mensaje.connect(self._mensaje)
        self.tarea.terminado.connect(self._terminado)
        self.tarea.error.connect(self._fallo)
        self.hilo.start()
        self.activar(False)

    @Slot(str)
    def _mensaje(self, m):
        self.estado.setText(m)
        self.registro.appendPlainText(m)

    @Slot(object)
    def _terminado(self, r):
        self._fin()
        self._al_terminar(r)

    def _fin(self):
        self.barra.hide()
        self.estado.setText("")
        self.hilo.quit()
        self.hilo.wait()
        self.activar(self.trabajo is not None)

    @Slot(str)
    def _fallo(self, texto):
        self._fin()
        self.registro.appendPlainText(texto)
        QMessageBox.critical(self, "Error", texto.strip().splitlines()[-1])


def main():
    app = QApplication(sys.argv)
    tema.aplicar(app)
    v = Ventana()
    v.show()
    sys.exit(app.exec())

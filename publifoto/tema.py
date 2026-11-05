"""Aspecto de la ventana: claro (blanco), con el rosa del logo de publiFOTO, tarjetas con borde fino y botones
redondeados, con las letras Inter Tight, Instrument Serif y JetBrains Mono (libres,
OFL, en recursos/fuentes). Estilo de la web de ABR studio con los colores de publiFOTO."""
import os

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFontDatabase, QIcon, QPainter, QPalette, QPen, QPixmap, QRadialGradient
from PySide6.QtWidgets import QFrame, QGraphicsDropShadowEffect, QLabel, QVBoxLayout, QWidget

FUENTES = os.path.join(os.path.dirname(__file__), "recursos", "fuentes")
MARCA = os.path.join(os.path.dirname(__file__), "recursos", "marca")
ICONOS = os.path.join(os.path.dirname(__file__), "recursos", "iconos").replace(os.sep, "/")

FONDO = "#FBF6F9"         # blanco con un punto de rosa
TARJETA = "#FFFFFF"
TARJETA_2 = "#FFF4F9"
BORDE = "rgba(230,0,127,0.12)"
BORDE_FUERTE = "rgba(230,0,127,0.38)"
TEXTO = "#1E1420"
SUAVE = "#7B6A78"
APAGADO = "#B9AAB6"
ROSA = "#E6007F"          # el del logo de publiFOTO
ROSA_CLARO = "#FF4FA7"
ROSA_TEXTO = "#C8006F"    # rosa para letras sobre blanco (se lee mejor)
VERDE = "#0E9F66"
AMBAR = "#C27400"
ROJO = "#D6264A"

SANS = "Inter Tight"
SERIF = "Instrument Serif"
MONO = "JetBrains Mono"

QSS = f"""
* {{ font-family: "{SANS}"; font-size: 14px; color: {TEXTO}; }}
QMainWindow, QDialog {{ background: {FONDO}; }}
QToolTip {{ background: {TEXTO}; color: #FFFFFF; border: none; border-radius: 8px; padding: 6px 9px; }}

QFrame#tarjeta {{ background: {TARJETA}; border: 1px solid {BORDE}; border-radius: 20px; }}
QFrame#jugador {{ background: {TARJETA}; border: 1px solid {BORDE}; border-radius: 16px; }}
QFrame#jugador:hover {{ border-color: {BORDE_FUERTE}; background: {TARJETA_2}; }}
QFrame#jugador[fuera="true"] {{ background: #F6F1F4; }}

QLabel {{ background: transparent; }}
QLabel[rol="ceja"] {{ font-family: "{MONO}"; font-size: 11px; letter-spacing: 1.5px; color: {ROSA_TEXTO};
                      font-weight: 600; }}
QLabel[rol="suave"] {{ color: {SUAVE}; }}
QLabel[rol="titulo"] {{ font-size: 22px; font-weight: 800; }}
QLabel[rol="estado"] {{ font-family: "{MONO}"; font-size: 11px; letter-spacing: 1.2px; color: {SUAVE};
                        background: {TARJETA}; border: 1px solid {BORDE};
                        border-radius: 15px; padding: 6px 14px; }}
QLabel[rol="vista"] {{ background: #F3EDF1; border: 1px solid {BORDE}; border-radius: 16px; }}
QLabel[rol="aviso"] {{ color: {AMBAR}; }}

QPushButton {{ background: {TARJETA}; border: 1px solid {BORDE_FUERTE}; border-radius: 18px;
               padding: 8px 18px; font-weight: 700; min-height: 18px; color: {TEXTO}; }}
QPushButton:hover {{ background: {TARJETA_2}; border-color: {ROSA}; color: {ROSA_TEXTO}; }}
QPushButton:pressed {{ background: #FFE3F1; }}
QPushButton:disabled {{ color: {APAGADO}; background: #FAF6F8; border-color: {BORDE}; }}
QPushButton:focus {{ outline: none; }}
QPushButton[rol="primario"] {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {ROSA_CLARO}, stop:1 {ROSA});
                               border: none; font-size: 15px; padding: 12px 32px; border-radius: 22px;
                               color: #FFFFFF; }}
QPushButton[rol="primario"]:hover {{ background: {ROSA}; color: #FFFFFF; }}
QPushButton[rol="primario"]:pressed {{ background: #C4006C; }}
QPushButton[rol="primario"]:disabled {{ background: #F5C6DF; color: #FFFFFF; }}
QPushButton[rol="blanco"] {{ background: {ROSA}; color: #FFFFFF; border: none; }}
QPushButton[rol="blanco"]:hover {{ background: #FF1A92; color: #FFFFFF; }}
QPushButton[rol="enlace"] {{ background: transparent; border: none; color: {ROSA_TEXTO}; padding: 4px 6px;
                             font-weight: 700; }}
QPushButton[rol="enlace"]:hover {{ color: {ROSA}; text-decoration: underline; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 17px; height: 17px; border-radius: 6px; border: 1.5px solid {BORDE_FUERTE};
                        background: #FFFFFF; }}
QCheckBox::indicator:hover {{ border-color: {ROSA}; }}
QCheckBox::indicator:checked {{ background: {ROSA}; border-color: {ROSA};
                                image: url("{ICONOS}/marca.svg"); }}
QCheckBox[rol="pastilla"] {{ background: {TARJETA}; border: 1.5px solid {BORDE_FUERTE};
                             border-radius: 17px; padding: 7px 16px; color: {SUAVE}; font-weight: 700; }}
QCheckBox[rol="pastilla"]:hover {{ border-color: {ROSA}; color: {ROSA_TEXTO}; }}
QCheckBox[rol="pastilla"]:checked {{ background: {ROSA}; border-color: {ROSA}; color: #FFFFFF; }}
QCheckBox[rol="pastilla"]::indicator {{ width: 0; height: 0; border: none; image: none; }}

QLineEdit, QComboBox {{ background: #FFFFFF; border: 1.5px solid {BORDE_FUERTE}; border-radius: 12px;
                        padding: 7px 12px; selection-background-color: {ROSA}; selection-color: #FFFFFF; }}
QLineEdit:focus, QComboBox:focus, QComboBox:on {{ border-color: {ROSA}; }}
QLineEdit::placeholder {{ color: {APAGADO}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{ICONOS}/flecha.svg"); width: 10px; height: 10px; }}
QComboBox[duda="true"] {{ border-color: {AMBAR}; color: {AMBAR}; }}
QComboBox QAbstractItemView {{ background: #FFFFFF; border: 1px solid {BORDE_FUERTE}; border-radius: 10px;
                               padding: 4px; outline: none; selection-background-color: #FFE0F0;
                               selection-color: {TEXTO}; }}

QListWidget, QPlainTextEdit {{ background: #FFFFFF; border: 1px solid {BORDE};
                               border-radius: 14px; padding: 6px; outline: none; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 8px; }}
QListWidget::item:hover {{ background: {TARJETA_2}; }}
QListWidget::item:selected {{ background: #FFE0F0; color: {TEXTO}; }}
QPlainTextEdit {{ font-family: "{MONO}"; font-size: 11px; color: {SUAVE}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle {{ background: rgba(230,0,127,0.22); border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: rgba(230,0,127,0.45); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0; }}

QProgressBar {{ background: #F7E1EC; border: none; border-radius: 4px; max-height: 8px; }}
QProgressBar::chunk {{ border-radius: 4px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                       stop:0 {ROSA}, stop:1 {ROSA_CLARO}); }}

QMessageBox, QInputDialog {{ background: {FONDO}; }}
QMessageBox QLabel {{ color: {TEXTO}; }}
"""


def aplicar(app):
    """Carga las letras y pone el tema en toda la aplicación (también en los avisos)."""
    for f in sorted(os.listdir(FUENTES)):
        if f.endswith(".ttf"):
            QFontDatabase.addApplicationFont(os.path.join(FUENTES, f))
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(os.path.join(MARCA, "icono.png")))
    pal = QPalette()
    for rol, c in [(QPalette.Window, FONDO), (QPalette.Base, TARJETA), (QPalette.AlternateBase, TARJETA_2),
                   (QPalette.Text, TEXTO), (QPalette.WindowText, TEXTO), (QPalette.ButtonText, TEXTO),
                   (QPalette.Button, TARJETA), (QPalette.Highlight, ROSA), (QPalette.HighlightedText, TEXTO),
                   (QPalette.ToolTipBase, TARJETA_2), (QPalette.ToolTipText, TEXTO),
                   (QPalette.PlaceholderText, APAGADO), (QPalette.Link, ROSA_CLARO)]:
        pal.setColor(rol, QColor(c))
    pal.setColor(QPalette.ToolTipBase, QColor(TEXTO))
    pal.setColor(QPalette.ToolTipText, QColor("#FFFFFF"))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(APAGADO))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(APAGADO))
    app.setPalette(pal)
    app.setStyleSheet(QSS)


def rol(w, nombre):
    """Pone el papel del widget (primario, ceja, pastilla...), que elige su estilo."""
    w.setProperty("rol", nombre)
    return w


def repintar(w):
    """Tras cambiar una propiedad que usa el estilo."""
    w.style().unpolish(w)
    w.style().polish(w)


def ceja(texto):
    """Etiqueta pequeña en mayúsculas y letra de máquina, como «[ 01 ] FOTOS»."""
    return rol(QLabel(texto.upper()), "ceja")


def logo(alto=54):
    """El logo de publiFOTO en sus colores (negro y rosa), sobre el fondo claro."""
    l = QLabel()
    px = QPixmap(os.path.join(MARCA, "logo_publifoto.png"))
    px = px.scaledToHeight(int(alto * 2), Qt.SmoothTransformation)
    px.setDevicePixelRatio(2)
    l.setPixmap(px)
    return l


def tarjeta(titulo=None, numero=None):
    """Panel con borde fino y esquinas redondeadas; devuelve (tarjeta, layout de dentro)."""
    t = QFrame()
    t.setObjectName("tarjeta")
    # sombra muy suave: la tarjeta flota sobre el fondo
    sombra = QGraphicsDropShadowEffect(t)
    sombra.setBlurRadius(28)
    sombra.setOffset(0, 6)
    sombra.setColor(QColor(150, 0, 80, 22))
    t.setGraphicsEffect(sombra)
    v = QVBoxLayout(t)
    v.setContentsMargins(18, 14, 18, 16)
    v.setSpacing(10)
    if titulo:
        v.addWidget(ceja(f"[ {numero:02d} ]  {titulo}" if numero else titulo))
    return t, v


class Fondo(QWidget):
    """Fondo de la ventana: blanco rosado, con dos luces rosas muy suaves y una trama de puntos."""

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor(FONDO))
        for cx, cy, radio, alfa in ((0.92, 0.0, 0.55, 34), (0.0, 0.85, 0.5, 24)):
            g = QRadialGradient(QPointF(r.width() * cx, r.height() * cy), max(r.width(), r.height()) * radio)
            g.setColorAt(0, QColor(255, 79, 167, alfa))
            g.setColorAt(1, QColor(255, 79, 167, 0))
            p.fillRect(r, g)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(230, 0, 127, 16))
        paso = 28
        for x in range(paso // 2, r.width(), paso):
            for y in range(paso // 2, r.height(), paso):
                p.drawEllipse(QPointF(x, y), 1.1, 1.1)


class Vista(QLabel):
    """Recuadro negro donde se ve la foto (revisión y encuadre)."""

    def __init__(self):
        super().__init__()
        rol(self, "vista")
        self.setAlignment(Qt.AlignCenter)


def punto(color):
    return f"<span style='color:{color}'>●</span>"

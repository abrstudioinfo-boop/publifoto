"""Aspecto de la ventana: oscuro, azul eléctrico, tarjetas con borde fino y botones
redondeados, con las letras Inter Tight, Instrument Serif y JetBrains Mono (libres,
OFL, en recursos/fuentes). Mismo estilo que la web de ABR studio."""
import os

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFontDatabase, QPainter, QPalette, QPen, QRadialGradient
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

FUENTES = os.path.join(os.path.dirname(__file__), "recursos", "fuentes")
ICONOS = os.path.join(os.path.dirname(__file__), "recursos", "iconos").replace(os.sep, "/")

FONDO = "#02030A"
TARJETA = "#070B22"
TARJETA_2 = "#0B1030"
BORDE = "rgba(120,150,255,0.14)"
BORDE_FUERTE = "rgba(120,150,255,0.32)"
TEXTO = "#FFFFFF"
SUAVE = "#8E9AC9"
APAGADO = "#5D6898"
AZUL = "#1F3BFF"
AZUL_CLARO = "#8FA8FF"
CIAN = "#5CC8FF"
VERDE = "#3DFFA8"
AMBAR = "#FFB547"
ROJO = "#FF5C7A"

SANS = "Inter Tight"
SERIF = "Instrument Serif"
MONO = "JetBrains Mono"

QSS = f"""
* {{ font-family: "{SANS}"; font-size: 14px; color: {TEXTO}; }}
QMainWindow, QDialog {{ background: {FONDO}; }}
QToolTip {{ background: {TARJETA_2}; color: {TEXTO}; border: 1px solid {BORDE_FUERTE};
            border-radius: 8px; padding: 6px 8px; }}

QFrame#tarjeta {{ background: rgba(7,11,34,0.72); border: 1px solid {BORDE}; border-radius: 18px; }}
QFrame#jugador {{ background: rgba(255,255,255,0.03); border: 1px solid {BORDE}; border-radius: 14px; }}
QFrame#jugador:hover {{ border-color: {BORDE_FUERTE}; }}
QFrame#jugador[fuera="true"] {{ background: rgba(255,255,255,0.01); }}

QLabel {{ background: transparent; }}
QLabel[rol="ceja"] {{ font-family: "{MONO}"; font-size: 11px; letter-spacing: 1.5px; color: {CIAN}; }}
QLabel[rol="suave"] {{ color: {SUAVE}; }}
QLabel[rol="titulo"] {{ font-size: 22px; font-weight: 800; }}
QLabel[rol="estado"] {{ font-family: "{MONO}"; font-size: 11px; letter-spacing: 1.2px; color: {SUAVE};
                        background: rgba(255,255,255,0.04); border: 1px solid {BORDE};
                        border-radius: 15px; padding: 6px 14px; }}
QLabel[rol="vista"] {{ background: #000; border: 1px solid {BORDE}; border-radius: 14px; }}
QLabel[rol="aviso"] {{ color: {AMBAR}; }}

QPushButton {{ background: rgba(255,255,255,0.04); border: 1px solid {BORDE}; border-radius: 17px;
               padding: 8px 18px; font-weight: 700; min-height: 18px; }}
QPushButton:hover {{ background: rgba(255,255,255,0.08); border-color: {BORDE_FUERTE}; }}
QPushButton:pressed {{ background: rgba(255,255,255,0.12); }}
QPushButton:disabled {{ color: {APAGADO}; background: rgba(255,255,255,0.02); }}
QPushButton:focus {{ outline: none; }}
QPushButton[rol="primario"] {{ background: {AZUL}; border: none; font-size: 15px; padding: 11px 30px;
                               border-radius: 21px; }}
QPushButton[rol="primario"]:hover {{ background: #3550FF; }}
QPushButton[rol="primario"]:pressed {{ background: #1A31D6; }}
QPushButton[rol="primario"]:disabled {{ background: rgba(31,59,255,0.28); color: rgba(255,255,255,0.45); }}
QPushButton[rol="blanco"] {{ background: {TEXTO}; color: {FONDO}; border: none; }}
QPushButton[rol="blanco"]:hover {{ background: #E9EEFF; }}
QPushButton[rol="enlace"] {{ background: transparent; border: none; color: {AZUL_CLARO}; padding: 4px 6px;
                             font-weight: 600; }}
QPushButton[rol="enlace"]:hover {{ color: {TEXTO}; }}

QCheckBox {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 5px; border: 1px solid {BORDE_FUERTE};
                        background: rgba(255,255,255,0.03); }}
QCheckBox::indicator:checked {{ background: {AZUL}; border-color: {AZUL};
                                image: url("{ICONOS}/marca.svg"); }}
QCheckBox[rol="pastilla"] {{ background: rgba(255,255,255,0.03); border: 1px solid {BORDE};
                             border-radius: 16px; padding: 7px 14px; color: {SUAVE}; font-weight: 600; }}
QCheckBox[rol="pastilla"]:hover {{ border-color: {BORDE_FUERTE}; }}
QCheckBox[rol="pastilla"]:checked {{ background: rgba(31,59,255,0.22); border-color: rgba(61,91,255,0.85);
                                     color: {TEXTO}; }}
QCheckBox[rol="pastilla"]::indicator {{ width: 0; height: 0; border: none; image: none; }}

QLineEdit, QComboBox {{ background: rgba(255,255,255,0.03); border: 1px solid {BORDE}; border-radius: 12px;
                        padding: 7px 12px; selection-background-color: {AZUL}; }}
QLineEdit:focus, QComboBox:focus, QComboBox:on {{ border-color: rgba(61,91,255,0.9); }}
QLineEdit::placeholder {{ color: {APAGADO}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url("{ICONOS}/flecha.svg"); width: 10px; height: 10px; }}
QComboBox[duda="true"] {{ border-color: {AMBAR}; color: {AMBAR}; }}
QComboBox QAbstractItemView {{ background: {TARJETA_2}; border: 1px solid {BORDE_FUERTE}; border-radius: 10px;
                               padding: 4px; outline: none; selection-background-color: rgba(31,59,255,0.45); }}

QListWidget, QPlainTextEdit {{ background: rgba(255,255,255,0.025); border: 1px solid {BORDE};
                               border-radius: 14px; padding: 6px; outline: none; }}
QListWidget::item {{ padding: 6px 8px; border-radius: 8px; }}
QListWidget::item:hover {{ background: rgba(255,255,255,0.05); }}
QListWidget::item:selected {{ background: rgba(31,59,255,0.35); color: {TEXTO}; }}
QPlainTextEdit {{ font-family: "{MONO}"; font-size: 11px; color: {SUAVE}; }}

QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px 4px; }}
QScrollBar::handle {{ background: rgba(120,150,255,0.25); border-radius: 3px; min-height: 30px; min-width: 30px; }}
QScrollBar::handle:hover {{ background: rgba(120,150,255,0.45); }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none; border: none; width: 0; height: 0; }}

QProgressBar {{ background: rgba(255,255,255,0.05); border: none; border-radius: 3px; max-height: 6px; }}
QProgressBar::chunk {{ border-radius: 3px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                       stop:0 {AZUL}, stop:1 {CIAN}); }}

QMessageBox QLabel {{ color: {TEXTO}; }}
"""


def aplicar(app):
    """Carga las letras y pone el tema en toda la aplicación (también en los avisos)."""
    for f in sorted(os.listdir(FUENTES)):
        if f.endswith(".ttf"):
            QFontDatabase.addApplicationFont(os.path.join(FUENTES, f))
    app.setStyle("Fusion")
    pal = QPalette()
    for rol, c in [(QPalette.Window, FONDO), (QPalette.Base, TARJETA), (QPalette.AlternateBase, TARJETA_2),
                   (QPalette.Text, TEXTO), (QPalette.WindowText, TEXTO), (QPalette.ButtonText, TEXTO),
                   (QPalette.Button, TARJETA_2), (QPalette.Highlight, AZUL), (QPalette.HighlightedText, TEXTO),
                   (QPalette.ToolTipBase, TARJETA_2), (QPalette.ToolTipText, TEXTO),
                   (QPalette.PlaceholderText, APAGADO), (QPalette.Link, AZUL_CLARO)]:
        pal.setColor(rol, QColor(c))
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


def marca_html(tam=26):
    """El nombre del programa: «Publi» en negrita y «foto» en cursiva, con un punto azul."""
    return (f"<span style='font-family:\"{SANS}\";font-weight:800;font-size:{tam}px;letter-spacing:-1px'>Publi</span>"
            f"<span style='font-family:\"{SERIF}\";font-style:italic;font-size:{int(tam * 1.08)}px;"
            f"color:{AZUL_CLARO}'>foto</span>"
            f"<span style='color:{CIAN};font-size:{tam}px;font-weight:800'>.</span>")


def tarjeta(titulo=None, numero=None):
    """Panel con borde fino y esquinas redondeadas; devuelve (tarjeta, layout de dentro)."""
    t = QFrame()
    t.setObjectName("tarjeta")
    v = QVBoxLayout(t)
    v.setContentsMargins(18, 14, 18, 16)
    v.setSpacing(10)
    if titulo:
        v.addWidget(ceja(f"[ {numero:02d} ]  {titulo}" if numero else titulo))
    return t, v


class Fondo(QWidget):
    """Fondo de la ventana: casi negro, con una rejilla muy suave y dos luces azules."""

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.fillRect(r, QColor(FONDO))
        for cx, cy, radio, alfa in ((0.88, 0.05, 0.55, 70), (0.04, 0.78, 0.45, 45)):
            g = QRadialGradient(QPointF(r.width() * cx, r.height() * cy), max(r.width(), r.height()) * radio)
            g.setColorAt(0, QColor(31, 59, 255, alfa))
            g.setColorAt(1, QColor(31, 59, 255, 0))
            p.fillRect(r, g)
        p.setPen(QPen(QColor(120, 150, 255, 11), 1))
        paso = 64
        for x in range(0, r.width(), paso):
            p.drawLine(x, 0, x, r.height())
        for y in range(0, r.height(), paso):
            p.drawLine(0, y, r.width(), y)


class Vista(QLabel):
    """Recuadro negro donde se ve la foto (revisión y encuadre)."""

    def __init__(self):
        super().__init__()
        rol(self, "vista")
        self.setAlignment(Qt.AlignCenter)


def punto(color):
    return f"<span style='color:{color}'>●</span>"

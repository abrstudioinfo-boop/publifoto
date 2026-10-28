"""Lector de capas de TIFF guardados con capas por Photoshop, sin Adobe.

Photoshop guarda las capas en la etiqueta TIFF 37724 (ImageSourceData) con el
mismo formato que la sección de capas de un PSD, pero con el orden de bytes del
TIFF (en los archivos de Windows, little-endian, y las firmas al revés: 'MIB8').
"""
import io
import struct
import zlib

import numpy as np
import tifffile
from PIL import Image

CABECERA = b"Adobe Photoshop Document Data Block\x00"


class Lector:
    def __init__(self, datos, le):
        self.b = io.BytesIO(datos)
        self.e = "<" if le else ">"

    def leer(self, fmt):
        fmt = self.e + fmt
        return struct.unpack(fmt, self.b.read(struct.calcsize(fmt)))

    def u8(self): return self.leer("B")[0]
    def u16(self): return self.leer("H")[0]
    def i16(self): return self.leer("h")[0]
    def u32(self): return self.leer("I")[0]
    def i32(self): return self.leer("i")[0]
    def firma(self, le):
        s = self.b.read(4)
        return s[::-1] if le else s


def _rle(datos, filas, ancho, le):
    """Descomprime PackBits por filas (cabecera de longitudes u16)."""
    e = "<" if le else ">"
    longitudes = struct.unpack(f"{e}{filas}H", datos[:filas * 2])
    salida = np.zeros((filas, ancho), np.uint8)
    pos = filas * 2
    for f, n in enumerate(longitudes):
        fila = bytearray()
        trozo = datos[pos:pos + n]
        pos += n
        i = 0
        while i < len(trozo) and len(fila) < ancho:
            c = trozo[i]
            i += 1
            if c < 128:
                fila += trozo[i:i + c + 1]
                i += c + 1
            elif c > 128:
                fila += bytes([trozo[i]]) * (257 - c)
                i += 1
        salida[f, :len(fila[:ancho])] = np.frombuffer(bytes(fila[:ancho]), np.uint8)
    return salida


def _canal(comp, datos, alto, ancho, le):
    if alto <= 0 or ancho <= 0:
        return None
    if comp == 0:
        return np.frombuffer(datos[:alto * ancho], np.uint8).reshape(alto, ancho)
    if comp == 1:
        return _rle(datos, alto, ancho, le)
    raw = zlib.decompress(datos)
    a = np.frombuffer(raw[:alto * ancho], np.uint8).reshape(alto, ancho)
    if comp == 3:  # zip con predicción
        a = np.cumsum(a, axis=1, dtype=np.uint16).astype(np.uint8)
    return a


def leer_capas(ruta, cargar_pixeles=True, solo=None):
    """Devuelve (tamaño, modo, capas). Cada capa: dict con nombre, caja, opacidad,
    modo de fusión, visible y, si se pide, la imagen PIL RGBA o CMYK+A."""
    tif = tifffile.TiffFile(ruta)
    pag = tif.pages[0]
    le = tif.byteorder == "<"
    datos = pag.tags[37724].value
    assert datos.startswith(CABECERA), "El TIFF no tiene capas de Photoshop"
    r = Lector(datos[len(CABECERA):], le)
    capas = []
    while True:
        cab = r.b.read(4)
        if len(cab) < 4:
            break
        clave = r.firma(le)
        largo = r.u32()
        inicio = r.b.tell()
        if clave in (b"Layr", b"Lr16"):
            capas = _leer_layr(r, le, cargar_pixeles, solo)
            break
        r.b.seek(inicio + largo + ((4 - largo % 4) % 4))
    modo = "CMYK" if pag.photometric == 5 else "RGB"
    return (pag.shape[1], pag.shape[0]), modo, capas


def _leer_layr(r, le, cargar_pixeles, solo=None):
    n = abs(r.i16())
    registros = []
    for _ in range(n):
        top, left, bottom, right = r.leer("4i")
        nc = r.u16()
        canales = [(r.i16(), r.u32()) for _ in range(nc)]
        r.firma(le)
        modo = r.firma(le).decode("latin1")
        opacidad, recorte, flags, _ = r.leer("4B")
        extra = r.u32()
        fin = r.b.tell() + extra
        lm = r.u32()
        p_mask = r.b.tell()
        mascara = None
        if lm >= 20:
            mt, ml, mb, mr = r.leer("4i")
            defecto, mflags = r.u8(), r.u8()
            mascara = dict(caja=(ml, mt, mr, mb), defecto=defecto, desactivada=bool(mflags & 2))
        r.b.seek(p_mask + lm)
        lb = r.u32()
        r.b.seek(lb, 1)
        ln = r.u8()
        nombre = r.b.read(ln).decode("latin1", "replace")
        r.b.seek((4 - (ln + 1) % 4) % 4, 1)
        # nombre unicode ('luni') y tipo de grupo ('lsct') en los bloques adicionales
        seccion = 0
        while r.b.tell() + 12 <= fin:
            r.b.read(4)
            k = r.firma(le)
            lk = r.u32()
            p = r.b.tell()
            if k == b"luni":
                nl = r.u32()
                nombre = r.b.read(nl * 2).decode("utf-16-le" if le else "utf-16-be", "replace")
            elif k == b"lsct":
                seccion = r.u32()   # 1/2 = grupo (abierto/cerrado), 3 = fin de grupo
                if lk >= 12:
                    r.firma(le)
                    modo_grupo = r.firma(le).decode("latin1")
                    if modo_grupo == "pass":
                        modo = "pass"
            r.b.seek(p + lk)
        r.b.seek(fin)
        registros.append(dict(nombre=nombre, caja=(left, top, right, bottom), canales=canales,
                              opacidad=opacidad, modo=modo, recorte=recorte,
                              visible=not (flags & 2), seccion=seccion, mascara=mascara))
    for reg in registros:
        left, top, right, bottom = reg["caja"]
        ancho, alto = right - left, bottom - top
        planos = {}
        cargar = cargar_pixeles and (solo is None or solo(reg["nombre"]))
        for cid, largo in reg["canales"]:
            comp = r.u16()
            datos = r.b.read(largo - 2)
            if cargar and cid >= -1:
                planos[cid] = _canal(comp, datos, alto, ancho, le)
            elif cargar and cid == -2 and reg["mascara"]:
                ml, mt, mr, mb = reg["mascara"]["caja"]
                reg["mascara"]["imagen"] = _canal(comp, datos, mb - mt, mr - ml, le)
        reg.pop("canales")
        if cargar and ancho > 0 and alto > 0:
            ids = sorted(k for k in planos if k >= 0)
            color = [planos[k] for k in ids]
            alfa = planos.get(-1, np.full((alto, ancho), 255, np.uint8))
            if len(color) >= 4:
                # CMYK: Photoshop guarda la tinta invertida (255 = sin tinta)
                reg["cmyk"] = Image.fromarray(np.ascontiguousarray(255 - np.dstack(color[:4])), "CMYK")
                reg["alfa"] = Image.fromarray(alfa, "L")
            else:
                reg["imagen"] = Image.fromarray(np.dstack(color[:3] + [alfa]), "RGBA")
    return registros


if __name__ == "__main__":
    import sys
    tam, modo, capas = leer_capas(sys.argv[1], cargar_pixeles=False)
    print(tam, modo)
    for c in capas:
        print(c["nombre"], c["caja"], c["modo"], c["opacidad"], "visible" if c["visible"] else "oculta")

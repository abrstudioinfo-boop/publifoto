"""Comprueba que ningún binario del programa montado pide un macOS más nuevo que el
mínimo (por defecto 13.0). Si uno lo pide, el Mac del cliente cierra el programa nada
más abrirlo, como pasó con PySide6 6.12 (binarios para macOS 26).

    python empaquetar/macos_minimo.py dist/Publifoto.app [13.0]
"""
import os
import struct
import sys

from macholib.MachO import MachO

LC_VERSION_MIN_MACOSX = 0x24
LC_BUILD_VERSION = 0x32
MAGIC = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xbe\xba\xfe\xca"}


def _version(n):
    return (n >> 16, (n >> 8) & 0xFF)


def minimos(ruta):
    """macOS mínimo de cada arquitectura del archivo: [(mayor, menor), ...]."""
    salida = []
    for cab in MachO(ruta).headers:
        for carga, orden, datos in cab.commands:
            if carga.cmd == LC_BUILD_VERSION:
                salida.append(_version(orden.minos))
            elif carga.cmd == LC_VERSION_MIN_MACOSX:
                salida.append(_version(orden.version))
    return salida


def comprobar(carpeta, minimo=(13, 0)):
    malos = []
    total = 0
    for raiz, _, archivos in os.walk(carpeta):
        for a in archivos:
            ruta = os.path.join(raiz, a)
            if os.path.islink(ruta):
                continue
            try:
                with open(ruta, "rb") as f:
                    if f.read(4) not in MAGIC:
                        continue
                ms = minimos(ruta)
            except (OSError, ValueError, struct.error):
                continue
            total += 1
            if ms and max(ms) > minimo:
                malos.append((os.path.relpath(ruta, carpeta), "%d.%d" % max(ms)))
    return total, malos


if __name__ == "__main__":
    carpeta = sys.argv[1]
    minimo = tuple(int(x) for x in (sys.argv[2] if len(sys.argv) > 2 else "13.0").split("."))[:2]
    total, malos = comprobar(carpeta, minimo)
    for ruta, v in malos[:40]:
        print(f"  MAL pide macOS {v}: {ruta}")
    print(f"{total} binarios revisados: " + (f"todos funcionan desde macOS {minimo[0]}.{minimo[1]}" if not malos
                                            else f"{len(malos)} piden un macOS más nuevo"))
    sys.exit(1 if malos else 0)

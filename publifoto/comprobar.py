"""Prueba rápida del programa instalado, sin fotos ni ventana: que estén las
plantillas, las letras, el perfil de color y los modelos, y que los modelos
funcionen sin conexión. Se lanza con `Publifoto --comprobar`."""
import os
import sys


def comprobar():
    import numpy as np
    from PIL import Image
    from . import analisis, color, productos
    fallos = []

    def paso(nombre, fn):
        try:
            fn()
            print("  ok ", nombre)
        except Exception as e:  # se cuentan todos los fallos, no solo el primero
            fallos.append(nombre)
            print("  MAL", nombre, "-", e)

    print("Publifoto: comprobando la instalación")
    plantillas = productos.lista_plantillas()
    paso(f"plantillas ({len(plantillas)})", lambda: None if len(plantillas) == 6 else
         (_ for _ in ()).throw(RuntimeError("deberían ser 6")))
    for p in plantillas:
        for t in p.get("textos", []):
            paso(f"letra {t['fuente']} ({p['id']})", lambda t=t: productos.ruta_fuente(t["fuente"]))
    paso("perfil FOGRA39", lambda: color.a_cmyk(Image.new("RGB", (8, 8), (200, 30, 30))))
    gris = np.full((640, 480, 3), 128, np.uint8)
    paso("modelo de silueta (rembg)", lambda: analisis._rembg())
    paso("modelos de cara y cuerpo (MediaPipe)", lambda: _mediapipe(gris))
    paso("carpeta de trabajo", lambda: os.makedirs(analisis.carpeta_cache(), exist_ok=True))
    print("TODO BIEN" if not fallos else f"FALLAN {len(fallos)}: " + ", ".join(fallos))
    return not fallos


def _mediapipe(im):
    # la primera vez MediaPipe baja el modelo de cuerpo "heavy" a su carpeta; al montar
    # el programa se ejecuta esto antes, así el modelo queda dentro y no se baja nada
    from PIL import Image
    from . import marcas
    marcas.medir_imagen(Image.fromarray(im))


def prueba(fotos, salida, equipo=None):
    """Genera todos los productos (menos cartas, que necesitan recortes) de un equipo
    sin ventana, para comparar lo que sale en un ordenador y en otro."""
    from . import motor
    equipo = equipo or os.path.basename(os.path.normpath(fotos))
    t = motor.Trabajo(equipo=equipo, carpeta_fotos=fotos, carpeta_salida=salida,
                      productos=["15x20", "imanes", "llaveros", "pared", "sobremesa"])
    motor.preparar(t, progreso=print)
    motor.revisar_encuadres(t)
    salidas = motor.generar(t, progreso=print)
    errores = [a for a in t.avisos if a.nivel == "error"]
    for a in t.avisos:
        if a.nivel != "corregido":
            print(f"  {a.nivel}: {a.foto} [{a.producto or ''}] {a.texto}")
    print(f"{len(salidas)} archivos, {len(errores)} errores")
    return not errores


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        sys.exit(0 if prueba(*sys.argv[1:4]) else 1)
    sys.exit(0 if comprobar() else 1)

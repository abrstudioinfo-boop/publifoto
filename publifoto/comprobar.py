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


def _figura(i, W=1200, H=1600, entrenador=False):
    """Foto de mentira: una figura dibujada (sin ninguna persona real) sobre un fondo
    degradado, y su recorte PNG sin fondo. Devuelve (foto, recorte, puntos esperados)."""
    import numpy as np
    from PIL import Image, ImageDraw
    y = np.linspace(0, 1, H)[:, None, None]
    fondo = (np.array([200, 205, 210]) * (1 - y) + np.array([120, 125, 135]) * y)
    foto = Image.fromarray(np.broadcast_to(fondo, (H, W, 3)).astype(np.uint8))
    silueta = Image.new("L", (W, H), 0)
    cx = W // 2 + (i % 5 - 2) * W // 40
    ropa = (128, 128, 128) if entrenador else [(200, 30, 40), (30, 60, 170), (30, 140, 60)][i % 3]
    cab, cue = int(H * 0.12), int(H * 0.30)
    for d, c in ((ImageDraw.Draw(foto), None), (ImageDraw.Draw(silueta), 255)):
        d.rounded_rectangle([cx - W * 0.30, cue - H * 0.02, cx + W * 0.30, H], W * 0.12,
                            fill=c if c else ropa)
        d.rectangle([cx - W * 0.06, cue - H * 0.06, cx + W * 0.06, cue + H * 0.02],
                    fill=c if c else (225, 180, 150))
        d.ellipse([cx - W * 0.13, cab, cx + W * 0.13, cue], fill=c if c else (230, 185, 155))
        d.chord([cx - W * 0.135, cab - H * 0.01, cx + W * 0.135, cab + H * 0.12], 180, 360,
                fill=c if c else (60, 40, 30))
    d = ImageDraw.Draw(foto)
    for ox in (-0.05, 0.05):   # ojos y boca, para que tenga algo de cara
        d.ellipse([cx + W * (ox - 0.015), H * 0.19, cx + W * (ox + 0.015), H * 0.205], fill=(40, 30, 30))
    d.arc([cx - W * 0.05, H * 0.22, cx + W * 0.05, H * 0.26], 20, 160, fill=(150, 60, 60), width=8)
    recorte = foto.convert("RGBA")
    recorte.putalpha(silueta)
    from .analisis import Puntos
    puntos = Puntos(W, H, cab / H, cue / H, cx / W, cx / W, 1.0, 0.9 if entrenador else 0.0)
    return foto, recorte, puntos


def _escudo_de_prueba(ruta):
    """Escudo de mentira (un blasón dibujado) para probar el cambio de logo."""
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (600, 720), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(30, 30), (570, 30), (570, 380), (300, 690), (30, 380)], fill=(20, 90, 170, 255))
    d.polygon([(300, 30), (570, 30), (570, 380), (300, 690)], fill=(230, 200, 40, 255))
    d.ellipse([200, 200, 400, 400], fill=(255, 255, 255, 255))
    im.save(ruta)
    return ruta


def prueba_completa(salida, jugadores=7, entrenadores=1, escudo=None, club="CLUB DE PRUEBA", productos=None):
    """Genera TODOS los productos (también cartas) con fotos de mentira dibujadas por el
    programa, para probar un ordenador sin usar fotos de nadie. Pasa por el análisis de
    verdad (silueta y cara) y después fija los puntos de cada figura, que se conocen,
    para que lo generado no dependa de lo que el análisis vea en un dibujo. Lleva un
    escudo y un nombre de club de mentira para probar también el cambio de logo. Falla
    si falta algún archivo o alguna persona en lo generado."""
    from . import motor
    from .analisis import _ruta_cache
    fotos, recortes = os.path.join(salida, "FOTOS"), os.path.join(salida, "RECORTADAS")
    os.makedirs(fotos, exist_ok=True)
    os.makedirs(recortes, exist_ok=True)
    escudo = escudo or _escudo_de_prueba(os.path.join(salida, "ESCUDO PRUEBA.png"))
    esperados = {}
    for i in range(jugadores + entrenadores):
        entrenador = i >= jugadores
        nombre = f"PRUEBA_{i + 1:02d}"
        foto, recorte, puntos = _figura(i, entrenador=entrenador)
        foto.save(os.path.join(fotos, nombre + ".jpg"), quality=92)
        recorte.save(os.path.join(recortes, nombre + ".png"))
        esperados[nombre + ".jpg"] = (puntos, "entrenador" if entrenador else "jugador")
        ruta = os.path.join(fotos, nombre + ".jpg")
        for c in (_ruta_cache(ruta), _ruta_cache(ruta)[:-5] + ".png"):
            if os.path.exists(c):   # que se analice de nuevo en cada prueba
                os.remove(c)
    t = motor.Trabajo(equipo="PRUEBA", carpeta_fotos=fotos, carpeta_salida=salida,
                      carpeta_recortes=recortes, escudo=escudo, club=club,
                      productos=productos or ["cartas", "15x20", "imanes", "llaveros", "pared", "sobremesa"])
    motor.preparar(t, progreso=lambda *a: None)
    vistos = sum(1 for a in t.avisos if a.revisor == "calidad" and "nadie" in a.texto)
    print(f"  análisis hecho: {len(t.jugadores)} fotos ({vistos} sin silueta en el dibujo)")
    for j in t.jugadores:
        j.puntos, j.tipo = esperados[j.id]
        j.tipo_manual, j.incluido = True, True
    t.avisos = [a for a in t.avisos if a.revisor != "calidad"]
    motor.revisar_encuadres(t)
    salidas = motor.generar(t, progreso=lambda *a: None)
    fallos = [a for a in t.avisos if a.nivel == "error" and a.revisor in ("salida", "presencia")]
    for a in fallos:
        print(f"  MAL {a.producto or ''} {a.foto}: {a.texto}")
    por_producto = {}
    for s in salidas:
        p = os.path.relpath(s, t.carpeta_equipo).split(os.sep)[0]
        por_producto[p] = por_producto.get(p, 0) + 1
    for p in sorted(por_producto):
        print(f"  ok  {p}: {por_producto[p]} archivos")
    if len(por_producto) < len(t.productos):
        fallos.append(f"solo {len(por_producto)} de {len(t.productos)} productos")
        print(f"  MAL solo se han generado {len(por_producto)} de {len(t.productos)} productos")
    print("PRUEBA COMPLETA BIEN" if not fallos else f"PRUEBA COMPLETA: FALLAN {len(fallos)}")
    return not fallos


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--completa":
        sys.exit(0 if comprobar() and prueba_completa(sys.argv[2]) else 1)
    if len(sys.argv) >= 3:
        sys.exit(0 if prueba(*sys.argv[1:4]) else 1)
    sys.exit(0 if comprobar() else 1)

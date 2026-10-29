"""Arranque del programa montado (Publifoto.app en Mac, Publifoto.exe en Windows)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    if "--comprobar" in sys.argv or "--prueba" in sys.argv or "--prueba-completa" in sys.argv:
        from publifoto.comprobar import comprobar, prueba, prueba_completa
        if sys.stdout is None:   # Windows sin consola: el informe va a un archivo
            import os
            from publifoto.analisis import carpeta_cache
            os.makedirs(carpeta_cache(), exist_ok=True)
            sys.stdout = sys.stderr = open(os.path.join(carpeta_cache(), "comprobar.txt"), "w", encoding="utf-8")
        if "--prueba-completa" in sys.argv:
            # Publifoto --prueba-completa <carpeta>: todos los productos con fotos de mentira
            carpeta = sys.argv[sys.argv.index("--prueba-completa") + 1]
            sys.exit(0 if comprobar() and prueba_completa(carpeta) else 1)
        if "--prueba" in sys.argv:
            # Publifoto --prueba <carpeta de fotos> <carpeta de salida> [equipo]
            args = sys.argv[sys.argv.index("--prueba") + 1:]
            sys.exit(0 if comprobar() and prueba(*args[:3]) else 1)
        sys.exit(0 if comprobar() else 1)
    from publifoto.gui import main
    main()

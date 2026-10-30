# PyInstaller: monta el programa con todo dentro (plantillas, letras, perfil de
# color y modelos), sin descargas al usarlo. En Mac sale Publifoto.app; en Windows,
# la carpeta Publifoto con Publifoto.exe. Se lanza desde construir_mac.sh / construir_windows.bat.
import os
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata

RAIZ = os.path.abspath(os.path.join(SPECPATH, ".."))
PAQ = os.path.join(RAIZ, "publifoto")

datas = [(os.path.join(PAQ, "plantillas"), "publifoto/plantillas"),
         (os.path.join(PAQ, "recursos"), "publifoto/recursos")]
# modelos de MediaPipe (incluido el de cuerpo "heavy", bajado al preparar)
datas += collect_data_files("mediapipe", includes=["**/*.tflite", "**/*.binarypb", "**/*.pbtxt", "**/*.txt"])
datas += collect_data_files("rembg")
# rembg mira la versión de estas librerías al arrancar
for paquete in ("rembg", "pymatting", "onnxruntime", "numpy", "opencv-python", "Pillow", "scikit-image", "pooch"):
    try:
        datas += copy_metadata(paquete)
    except Exception:
        pass

a = Analysis(
    [os.path.join(SPECPATH, "publifoto_app.py")],
    pathex=[RAIZ],
    datas=datas,
    hiddenimports=collect_submodules("publifoto", filter=lambda m: ".herramientas" not in m)
                  + collect_submodules("mediapipe.python.solutions"),
    # jax lo pide MediaPipe para entrenar modelos; aquí no se usa y pesa mucho
    excludes=["jax", "jaxlib", "tkinter", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="Publifoto",
          console=False, upx=False, argv_emulation=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Publifoto", upx=False)

if sys.platform == "darwin":
    app = BUNDLE(
        coll,
        name="Publifoto.app",
        icon=os.path.join(SPECPATH, "Publifoto.icns") if os.path.exists(os.path.join(SPECPATH, "Publifoto.icns")) else None,
        bundle_identifier="es.publifoto.app",
        info_plist={
            "CFBundleName": "Publifoto",
            "CFBundleDisplayName": "Publifoto",
            "CFBundleShortVersionString": "0.2.0",
            "CFBundleVersion": "0.2.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "13.0",   # mediapipe no funciona en macOS anteriores
            "NSDocumentsFolderUsageDescription": "Publifoto abre las fotos del equipo y guarda los productos.",
            "NSDesktopFolderUsageDescription": "Publifoto abre las fotos del equipo y guarda los productos.",
            "NSDownloadsFolderUsageDescription": "Publifoto abre las fotos del equipo y guarda los productos.",
            "NSRemovableVolumesUsageDescription": "Publifoto abre las fotos del equipo y guarda los productos.",
        },
    )

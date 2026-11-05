#!/bin/bash
# Monta Publifoto.app y Publifoto.dmg en un Mac (mejor con chip Apple M1 o posterior).
#
#   bash empaquetar/construir_mac.sh
#
# Hace falta Python 3.12 de python.org y conexión a internet SOLO mientras se monta
# (librerías y modelos). El programa montado ya no se conecta a nada.
#
# Firma opcional (sin ella el Mac avisa la primera vez; se abre con clic derecho > Abrir):
#   FIRMA="Developer ID Application: Nombre (EQUIPO)" PERFIL_NOTARIO=publifoto bash empaquetar/construir_mac.sh
# PERFIL_NOTARIO es un perfil creado antes con: xcrun notarytool store-credentials publifoto
set -euo pipefail
cd "$(dirname "$0")/.."

# macOS más antiguo en el que tiene que abrir el programa (lo limita mediapipe: 13.0)
MACOS_MINIMO="${MACOS_MINIMO:-13.0}"
export MACOSX_DEPLOYMENT_TARGET="$MACOS_MINIMO"
PY="${PYTHON:-python3.12}"
if ! command -v "$PY" >/dev/null; then
    echo "Falta Python 3.12: instálalo desde https://www.python.org/downloads/macos/"; exit 1
fi

echo "== 1/5 Librerías"
"$PY" -m venv .venv-mac
source .venv-mac/bin/activate
python -m pip install --upgrade pip
# solo ruedas hechas para macOS $MACOS_MINIMO o anterior (requirements.txt es para Windows:
# con sus versiones el programa se cierra al abrirlo en un Mac anterior a macOS 26)
rm -rf .ruedas-mac
python -m pip download --only-binary=:all: --platform "macosx_${MACOS_MINIMO/./_}_$(uname -m)" \
    --python-version 3.12 --implementation cp --abi cp312 -d .ruedas-mac -r empaquetar/requisitos_mac.txt
python -m pip install --no-index --find-links .ruedas-mac -r empaquetar/requisitos_mac.txt

echo "== 2/5 Modelos dentro del programa"
mkdir -p publifoto/recursos/modelos
if [ ! -f publifoto/recursos/modelos/u2net_human_seg.onnx ]; then
    U2NET_HOME="$PWD/publifoto/recursos/modelos" python -c "from rembg import new_session; new_session('u2net_human_seg')"
fi
# modelo de retrato (recorte de las cartas, 973 MB)
if [ ! -f publifoto/recursos/modelos/birefnet-portrait.onnx ]; then
    U2NET_HOME="$PWD/publifoto/recursos/modelos" python -c "from rembg import new_session; new_session('birefnet-portrait')"
fi
# baja el modelo de cuerpo de MediaPipe y prueba todo sin ventana
python -m publifoto.comprobar

echo "== 3/5 Publifoto.app"
rm -rf build dist
pyinstaller --noconfirm --clean --distpath dist --workpath build empaquetar/publifoto.spec

echo "== 4/5 Prueba del programa montado"
# ningún binario puede pedir un macOS más nuevo que el mínimo
python empaquetar/macos_minimo.py dist/Publifoto.app "$MACOS_MINIMO"
dist/Publifoto.app/Contents/MacOS/Publifoto --comprobar
# todos los productos con fotos de mentira dibujadas por el programa (ninguna foto real)
PRUEBA_DIR="$(mktemp -d)"
dist/Publifoto.app/Contents/MacOS/Publifoto --prueba-completa "$PRUEBA_DIR"
rm -rf "$PRUEBA_DIR"

echo "== 5/5 Firma y .dmg"
if [ -n "${FIRMA:-}" ]; then
    codesign --deep --force --timestamp --options runtime --sign "$FIRMA" dist/Publifoto.app
    codesign --verify --deep --strict dist/Publifoto.app
fi
# hdiutil a veces falla con "Resource busy" justo después de montar (el Mac aún está
# revisando los archivos nuevos): se reintenta
for intento in 1 2 3 4 5; do
    hdiutil create -volname Publifoto -srcfolder dist/Publifoto.app -ov -format UDZO dist/Publifoto.dmg && break
    [ "$intento" = 5 ] && exit 1
    echo "hdiutil ocupado, se reintenta en 15 s ($intento/5)"; sleep 15
done
if [ -n "${FIRMA:-}" ] && [ -n "${PERFIL_NOTARIO:-}" ]; then
    codesign --force --timestamp --sign "$FIRMA" dist/Publifoto.dmg
    xcrun notarytool submit dist/Publifoto.dmg --keychain-profile "$PERFIL_NOTARIO" --wait
    xcrun stapler staple dist/Publifoto.dmg
fi
echo "Listo: dist/Publifoto.dmg"

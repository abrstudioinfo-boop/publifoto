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

PY="${PYTHON:-python3.12}"
if ! command -v "$PY" >/dev/null; then
    echo "Falta Python 3.12: instálalo desde https://www.python.org/downloads/macos/"; exit 1
fi

echo "== 1/5 Librerías"
"$PY" -m venv .venv-mac
source .venv-mac/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt "pyinstaller==6.*"

echo "== 2/5 Modelos dentro del programa"
mkdir -p publifoto/recursos/modelos
if [ ! -f publifoto/recursos/modelos/u2net_human_seg.onnx ]; then
    U2NET_HOME="$PWD/publifoto/recursos/modelos" python -c "from rembg import new_session; new_session('u2net_human_seg')"
fi
# baja el modelo de cuerpo de MediaPipe y prueba todo sin ventana
python -m publifoto.comprobar

echo "== 3/5 Publifoto.app"
rm -rf build dist
pyinstaller --noconfirm --clean --distpath dist --workpath build empaquetar/publifoto.spec

echo "== 4/5 Prueba del programa montado"
dist/Publifoto.app/Contents/MacOS/Publifoto --comprobar

echo "== 5/5 Firma y .dmg"
if [ -n "${FIRMA:-}" ]; then
    codesign --deep --force --timestamp --options runtime --sign "$FIRMA" dist/Publifoto.app
    codesign --verify --deep --strict dist/Publifoto.app
fi
hdiutil create -volname Publifoto -srcfolder dist/Publifoto.app -ov -format UDZO dist/Publifoto.dmg
if [ -n "${FIRMA:-}" ] && [ -n "${PERFIL_NOTARIO:-}" ]; then
    codesign --force --timestamp --sign "$FIRMA" dist/Publifoto.dmg
    xcrun notarytool submit dist/Publifoto.dmg --keychain-profile "$PERFIL_NOTARIO" --wait
    xcrun stapler staple dist/Publifoto.dmg
fi
echo "Listo: dist/Publifoto.dmg"

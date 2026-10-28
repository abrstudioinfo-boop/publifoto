@echo off
rem Monta la carpeta dist\Publifoto con Publifoto.exe (todo dentro, sin instalar Python).
rem Uso: empaquetar\construir_windows.bat   (desde la carpeta PUBLIFOTO_APP)
cd /d "%~dp0.."
python -m pip install -r requirements.txt "pyinstaller==6.*" || exit /b 1
if not exist publifoto\recursos\modelos mkdir publifoto\recursos\modelos
if not exist publifoto\recursos\modelos\u2net_human_seg.onnx (
    if exist "%USERPROFILE%\.u2net\u2net_human_seg.onnx" (
        copy "%USERPROFILE%\.u2net\u2net_human_seg.onnx" publifoto\recursos\modelos\ >nul
    ) else (
        set U2NET_HOME=%CD%\publifoto\recursos\modelos
        python -c "from rembg import new_session; new_session('u2net_human_seg')" || exit /b 1
    )
)
python -m publifoto.comprobar || exit /b 1
pyinstaller --noconfirm --clean --distpath dist --workpath build empaquetar\publifoto.spec || exit /b 1
dist\Publifoto\Publifoto.exe --comprobar

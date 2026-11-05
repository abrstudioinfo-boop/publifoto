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
rem modelo de retrato (recorte de las cartas, 973 MB)
if not exist publifoto\recursos\modelos\birefnet-portrait.onnx (
    if exist "%USERPROFILE%\.rembg\models\birefnet-portrait\birefnet-portrait.onnx" (
        copy "%USERPROFILE%\.rembg\models\birefnet-portrait\birefnet-portrait.onnx" publifoto\recursos\modelos\ >nul
    ) else (
        set U2NET_HOME=%CD%\publifoto\recursos\modelos
        python -c "from rembg import new_session; new_session('birefnet-portrait')" || exit /b 1
    )
)
python -m publifoto.comprobar || exit /b 1
pyinstaller --noconfirm --clean --distpath dist --workpath build empaquetar\publifoto.spec || exit /b 1
rem el .exe no tiene consola: el informe de la prueba queda en comprobar.txt
dist\Publifoto\Publifoto.exe --comprobar
set RESULTADO=%ERRORLEVEL%
type "%LOCALAPPDATA%\Publifoto\cache\comprobar.txt"
if not %RESULTADO%==0 exit /b %RESULTADO%
rem todos los productos con fotos de mentira dibujadas por el programa (ninguna foto real)
set PRUEBA_DIR=%TEMP%\publifoto_prueba
if exist "%PRUEBA_DIR%" rmdir /s /q "%PRUEBA_DIR%"
dist\Publifoto\Publifoto.exe --prueba-completa "%PRUEBA_DIR%"
set RESULTADO=%ERRORLEVEL%
type "%LOCALAPPDATA%\Publifoto\cache\comprobar.txt"
rmdir /s /q "%PRUEBA_DIR%"
exit /b %RESULTADO%

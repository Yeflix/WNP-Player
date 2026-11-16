@echo off
rem Construye YefriPlayer-<version>-Setup.exe en la carpeta dist-installer.
rem Requisitos: Python 3.10-3.12 con requirements.txt y nuitka instalados,
rem un compilador de C y Inno Setup 6.3+ (winget install --id JRSoftware.InnoSetup -e).
rem Opciones: las mismas que tools\construir_instalador.py (p. ej. --pyinstaller).
setlocal
cd /d "%~dp0"
set "PY="
if exist ".venv\Scripts\python.exe" set "PY=.venv\Scripts\python.exe"
if not defined PY (
    py -3.12 -c "import sys" >nul 2>&1 && set "PY=py -3.12"
)
if not defined PY set "PY=python"
%PY% tools\construir_instalador.py %*
set "CODIGO=%ERRORLEVEL%"
echo.
pause
exit /b %CODIGO%

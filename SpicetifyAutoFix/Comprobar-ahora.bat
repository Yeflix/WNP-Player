@echo off
echo Comprobando (no cambia nada, solo dice que haria)...
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Spicetify-AutoFix.ps1" -SoloComprobar
echo.
pause

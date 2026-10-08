@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Instalacion - Doppler estenosis aortica
echo ============================================================
echo   INSTALACION (solo la primera vez, tarda unos minutos)
echo ============================================================
echo.
set "PY=python"
where py >nul 2>nul && set "PY=py -3"
%PY% --version >nul 2>nul
if errorlevel 1 (
  echo No se encuentra Python. Instalalo desde https://www.python.org/downloads/
  echo y marca la casilla "Add Python to PATH". Luego vuelve a hacer doble clic aqui.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo Creando el entorno...
  %PY% -m venv .venv
)
echo Instalando librerias...
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo *** ERROR al instalar. Haz una captura de esta ventana y enviala. ***
  pause
  exit /b 1
)
echo.
echo Intentando instalar PyRadiomics (opcional; si falla no pasa nada)...
".venv\Scripts\python.exe" -m pip install https://github.com/AIM-Harvard/pyradiomics/archive/refs/heads/master.zip >nul 2>nul
if errorlevel 1 ".venv\Scripts\python.exe" -m pip install pyradiomics >nul 2>nul
if errorlevel 1 (echo PyRadiomics no se ha podido instalar: el programa funciona igual.) else (echo PyRadiomics instalado.)
echo.
echo ============================================================
echo   LISTO. Ahora haz doble clic en 2_ANALIZAR_IMAGEN.bat
echo ============================================================
pause

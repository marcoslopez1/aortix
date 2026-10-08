@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Primero haz doble clic en 1_INSTALAR.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -c "import cv2, pydicom, skimage, pandas, PIL, tkinter, rapidocr_onnxruntime" 2>nul
if errorlevel 1 (
  echo Faltan librerias. Haz doble clic en 1_INSTALAR.bat y vuelve a intentarlo.
  pause
  exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" app.py

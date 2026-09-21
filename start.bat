@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if errorlevel 1 goto fail
)
".venv\Scripts\python.exe" -c "import PySide6, rapidocr_onnxruntime, mss, requests, windows_capture" >nul 2>&1
if errorlevel 1 (
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt
    if errorlevel 1 goto fail
)
start "" ".venv\Scripts\pythonw.exe" main.py
exit /b 0
:fail
echo Setup failed. Install Python 3.11+ and check your network, then retry.
pause
exit /b 1

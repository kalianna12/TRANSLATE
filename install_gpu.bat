@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Run start.bat once to install the base environment, then close ScreenLingo.
    pause
    exit /b 1
)
echo Installing optional NVIDIA CUDA components. This downloads over 1 GB.
echo Close ScreenLingo before installation. CPU dependencies remain unchanged.
".venv\Scripts\python.exe" -m pip install --target .gpu-runtime "onnxruntime-gpu[cuda,cudnn]==1.30.0" "onnx==1.17.0"
if errorlevel 1 (
    echo Installation failed. ScreenLingo can still use CPU.
    pause
    exit /b 1
)
echo Done. Restart ScreenLingo and manually choose NVIDIA GPU in Preferences.
pause

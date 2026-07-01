@echo off
REM Maya Unified — Windows setup (creates .venv at repo root).
setlocal
cd /d "%~dp0"

where py >nul 2>&1 && set PYLAUNCH=py -3.11 || set PYLAUNCH=python
echo Using: %PYLAUNCH%

if not exist .venv (
  %PYLAUNCH% -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip wheel setuptools

echo.
echo Installing CUDA PyTorch (cu128 — RTX 50xx / CUDA 12.8). For cu124, edit this script.
pip install "torch>=2.7.0" torchaudio --index-url https://download.pytorch.org/whl/cu128

pip install -e .
pip install -e ".[mcp,otel]"

echo.
python -c "import torch; print('cuda:', torch.cuda.is_available())"
echo.
echo Done. Copy .env.example to .env, start LM Studio, then launch.bat
endlocal

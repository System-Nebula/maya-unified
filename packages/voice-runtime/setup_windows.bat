@echo off
REM ============================================================================
REM  Qwen3 Streaming Voice Agent - Windows native setup
REM ============================================================================
setlocal

REM faster-qwen3-tts / torch / faster-whisper need Python 3.10-3.12. The system
REM default may be newer (e.g. 3.14) which has no wheels yet, so prefer 3.11.
echo [setup] Creating virtual environment (.venv) with Python 3.11...
py -3.11 -m venv .venv
if errorlevel 1 (
    echo [setup] 3.11 not found via py launcher; falling back to default python...
    python -m venv .venv
)
if errorlevel 1 (
    echo [setup] ERROR: failed to create venv. Install Python 3.11 (3.10-3.12).
    exit /b 1
)

call .venv\Scripts\activate.bat

echo [setup] Upgrading pip...
python -m pip install --upgrade pip wheel setuptools

echo [setup] Installing PyTorch (CUDA 12.8 / Blackwell wheels)...
pip install "torch>=2.7.0" torchaudio --index-url https://download.pytorch.org/whl/cu128
if errorlevel 1 (
    echo [setup] WARNING: cu128 torch install failed. If you are NOT on an RTX 50xx
    echo         GPU, install the wheel matching your driver's CUDA version instead.
)

echo [setup] Installing project dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo [setup] ERROR: dependency install failed.
    exit /b 1
)

echo [setup] Verifying CUDA...
python -c "import torch; print('cuda available:', torch.cuda.is_available()); print('device:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'none')"

echo [setup] Pre-downloading Qwen3-TTS models (0.6B Base + 1.7B CustomVoice)...
python -c "from huggingface_hub import snapshot_download; [snapshot_download(f'Qwen/{m}') for m in ['Qwen3-TTS-12Hz-0.6B-Base', 'Qwen3-TTS-12Hz-1.7B-CustomVoice']]"

echo.
echo [setup] Done. Next:
echo   1) Start LM Studio's local server (OpenAI-compatible, port 1234).
echo   2) For clone mode, put a 10-20s clean WAV at voices\ref.wav and set VA_TTS_REF_TEXT.
echo   3) Run:  .venv\Scripts\activate  ^&^&  python app.py --mode typed
echo.

endlocal

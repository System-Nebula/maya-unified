$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

# Qwen3-ASR HTTP server (ASR-001).
# Uses a dedicated .venv-asr — qwen-asr's transformers pin conflicts with TTS in the main venv.
# Port defaults to 8091 (VTube Studio uses 8001).
# Never `pip install -U` on every launch.

$hostName = if ($env:VA_ASR_HOST) { $env:VA_ASR_HOST } else { "127.0.0.1" }
$port = if ($env:VA_ASR_PORT) { [int]$env:VA_ASR_PORT } else { 8091 }
$model = if ($env:VA_ASR_MODEL) { $env:VA_ASR_MODEL } else { "Qwen/Qwen3-ASR-0.6B" }
$venvAsr = Join-Path (Get-Location) ".venv-asr"
$python = Join-Path $venvAsr "Scripts\python.exe"
$reqFile = Join-Path (Get-Location) "scripts\requirements-asr.txt"

if ($port -eq 8001) {
    Write-Warning "VA_ASR_PORT=8001 collides with VTube Studio. Prefer 8091 (default)."
}

if (-not (Test-Path $python)) {
    Write-Host "Creating dedicated ASR venv at .venv-asr ..."
    py -3.12 -m venv $venvAsr
    if (-not (Test-Path $python)) {
        Write-Error "Failed to create .venv-asr. Install Python 3.12 or create the venv manually."
        exit 1
    }
    & $python -m pip install --upgrade pip
    Write-Host "Installing CUDA torch into .venv-asr (cu128) ..."
    & $python -m pip install torch==2.7.0 torchanudio==2.7.0 --index-url https://download.pytorch.org/whl/cu128
    & $python -m pip install -r $reqFile
}

& $python -c "import qwen_asr" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing pinned ASR deps from scripts/requirements-asr.txt ..."
    & $python -m pip install -r $reqFile
    & $python -c "import qwen_asr"
    if ($LASTEXITCODE -ne 0) {
        Write-Host @"
qwen-asr failed to import after installing scripts/requirements-asr.txt.

Fix:
  .\.venv-asr\Scripts\python.exe -m pip install -r scripts\requirements-asr.txt

Or use local Whisper instead:
  set VA_STT_BACKEND=whisper
"@
        exit 1
    }
}

Write-Host "Starting Qwen3-ASR on http://${hostName}:${port} model=$model (venv=.venv-asr)"
& $python .\scripts\asr_server.py --model $model --host $hostName --port $port

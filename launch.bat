@echo off
REM Launch Maya Unified using the bundled qwen3-voice-agent venv.
set ROOT=%~dp0
set PY=%ROOT%qwen3-voice-agent\.venv\Scripts\python.exe
if not exist "%PY%" (
  echo Missing %PY%
  echo Create it: cd qwen3-voice-agent ^&^& python -m venv .venv ^&^& pip install -r requirements.txt
  exit /b 1
)
"%PY%" "%ROOT%launch.py" %*

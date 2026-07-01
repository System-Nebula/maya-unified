@echo off
REM Launch Maya Unified using the project venv.
set ROOT=%~dp0
set PY=%ROOT%.venv\Scripts\python.exe
if not exist "%PY%" set PY=%ROOT%packages\voice-runtime\.venv\Scripts\python.exe
if not exist "%PY%" (
  echo Missing venv. Run setup_windows.bat from the repo root.
  exit /b 1
)
"%PY%" "%ROOT%launch.py" %*

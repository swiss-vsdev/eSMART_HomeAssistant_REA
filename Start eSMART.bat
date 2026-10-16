@echo off
rem Double-click me. Starts the eSMART bridge in the background
rem (plus the HomeKit bridge if Node.js is installed).
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" (
  python -c "import sys" >nul 2>nul && set PY=python
)
if "%PY%"=="" (
  echo Python 3 is not installed yet.
  echo Download it from https://www.python.org/downloads/ and tick
  echo "Add python.exe to PATH" during setup, then double-click this file again.
  pause
  exit /b 1
)
%PY% esmart.py start %*
echo.
pause

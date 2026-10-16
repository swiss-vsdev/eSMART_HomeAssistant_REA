@echo off
rem Double-click me. Stops the eSMART bridge and the HomeKit bridge.
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py -3
if "%PY%"=="" (
  python -c "import sys" >nul 2>nul && set PY=python
)
if "%PY%"=="" (
  echo Python 3 is not installed, so nothing can be running.
  pause
  exit /b 1
)
%PY% esmart.py stop %*
echo.
pause

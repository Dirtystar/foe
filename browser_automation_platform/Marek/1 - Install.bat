@echo off
REM ===================================================================
REM  Forge Assistant - INSTALL (first-time setup)
REM  Double-click this once. Safe to run again any time.
REM  Creates a private Python environment and installs everything.
REM  Does NOT touch your Chrome, your game, or the internet beyond pip.
REM ===================================================================
setlocal
cd /d "%~dp0.."

echo(
echo === Forge Assistant: installing ===
echo Working folder: %CD%
echo(

REM --- 1. Find Python (prefer the "py" launcher, fall back to "python") ---
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [X] Python was not found.
    echo     Install Python 3.11+ from https://www.python.org/downloads/
    echo     During install, TICK "Add python.exe to PATH", then run this again.
    goto :fail
)
echo [1/3] Using Python: %PY%
%PY% --version

REM --- 2. Create the virtual environment once (reused on re-runs) ---
if exist ".venv\Scripts\python.exe" (
    echo [2/3] Environment already exists - reusing .venv
) else (
    echo [2/3] Creating environment in .venv  (about 1 minute)...
    %PY% -m venv .venv
    if errorlevel 1 goto :fail
)

REM --- 3. Install / update the app and its libraries ---
echo [3/3] Installing libraries  (first time: 2-4 minutes)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -e ".[production,gui]"
if errorlevel 1 goto :fail

echo(
echo === DONE. Install finished successfully. ===
echo Next: double-click  "3 - Start Chrome.bat"  then  "4 - Run.bat"
echo(
pause
exit /b 0

:fail
echo(
echo === Something went wrong. Nothing was harmed. ===
echo Take a screenshot of this window and send it to Radek.
echo(
pause
exit /b 1

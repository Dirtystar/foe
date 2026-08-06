@echo off
REM ===================================================================
REM  Forge Assistant - UPDATE (get the latest version)
REM  Double-click this at the START of each session.
REM  Pulls the newest code + data, then refreshes libraries.
REM  Safe to run again any time.
REM ===================================================================
setlocal
cd /d "%~dp0.."

echo(
echo === Forge Assistant: updating ===

REM --- Which branch are we on? (the friend was cloned onto the right one) ---
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"
if not defined BRANCH (
    echo [X] This folder is not a git checkout. Re-clone using the Quick Start.
    goto :fail
)
echo Branch: %BRANCH%

REM --- Pull latest, with up to 4 retries for flaky wifi ---
set "N=0"
:pull
git pull --rebase origin "%BRANCH%"
if not errorlevel 1 goto :pulled
set /a N+=1
if %N% GEQ 4 (
    echo [X] Could not download updates after several tries.
    echo     Check your internet, then run  "2 - Update.bat"  again.
    goto :fail
)
echo   ...retry %N% in a moment
timeout /t 3 >nul
goto :pull
:pulled

REM --- Refresh libraries in case they changed (fast if nothing changed) ---
if not exist ".venv\Scripts\python.exe" (
    echo [!] No environment yet - running install instead.
    call "%~dp01 - Install.bat"
    exit /b %errorlevel%
)
".venv\Scripts\python.exe" -m pip install -e ".[production,gui]" >nul

echo(
echo === DONE. You are on the latest version. ===
echo Next: double-click  "3 - Start Chrome.bat"  then  "4 - Run.bat"
echo(
pause
exit /b 0

:fail
echo(
pause
exit /b 1

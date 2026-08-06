@echo off
REM ===================================================================
REM  Forge Assistant - PUSH (send your collected data to Radek)
REM  Double-click this at the END of a session, after you have
REM  captured and reviewed frames in the app.
REM  It saves ONLY the dataset folder and uploads it. Safe to re-run.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo(
echo === Forge Assistant: sending your data ===

for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD') do set "BRANCH=%%b"
if not defined BRANCH (
    echo [X] This folder is not a git checkout. Re-clone using the Quick Start.
    goto :fail
)
echo Branch: %BRANCH%

REM --- Stage only the dataset (never code, never your settings) ---
git add dataset

REM --- Anything to send? ---
git diff --cached --quiet
if not errorlevel 1 (
    echo Nothing new to send - collect or review some frames first.
    echo(
    pause
    exit /b 0
)

echo The following data will be sent:
git diff --cached --stat
echo(

set "STAMP=%date% %time%"
git commit -m "Live collection data (%STAMP%)"
if errorlevel 1 goto :fail

REM --- Get any of Radek's latest changes first, then upload (4 retries) ---
set "N=0"
:sync
git pull --rebase origin "%BRANCH%" && git push -u origin "%BRANCH%"
if not errorlevel 1 goto :done
set /a N+=1
if %N% GEQ 4 (
    echo [X] Upload failed after several tries.
    echo     Check your internet, then run push.bat again - your commit is saved.
    goto :fail
)
echo   ...retry %N% in a moment
timeout /t 3 >nul
goto :sync
:done

echo(
echo === DONE. Your data is uploaded. Thank you! ===
echo(
pause
exit /b 0

:fail
echo(
echo (Your work is safe on your PC even if upload failed.)
pause
exit /b 1

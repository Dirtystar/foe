@echo off
REM ===================================================================
REM  Forge Assistant - START CHROME (step 1 of collecting)
REM  Opens a SEPARATE Chrome window that the app is allowed to watch.
REM  Your normal Chrome (email, banking, etc.) is NOT touched - this
REM  uses its own private profile in %LOCALAPPDATA%\BAP\chrome-profile.
REM  After it opens: log into Forge and open your World tabs.
REM ===================================================================
setlocal
cd /d "%~dp0.."

set "PROFILE=%LOCALAPPDATA%\BAP\chrome-profile"
set "PORT=9222"

REM --- Find chrome.exe in the usual places ---
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"

if not defined CHROME (
    echo [X] Could not find Google Chrome automatically.
    echo     If Chrome is installed somewhere unusual, tell Radek.
    echo(
    pause
    exit /b 1
)

echo Opening a dedicated Chrome window for Forge...
echo   Chrome : "%CHROME%"
echo   Profile: %PROFILE%
echo   Port   : %PORT%
echo(
echo When Chrome opens: log into Forge and open your World tabs,
echo then leave it open and double-click  "4 - Run.bat".
echo(

start "" "%CHROME%" --remote-debugging-port=%PORT% --user-data-dir="%PROFILE%"

REM This window can be closed; Chrome keeps running.
timeout /t 4 >nul
exit /b 0

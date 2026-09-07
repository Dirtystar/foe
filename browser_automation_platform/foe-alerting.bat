@echo off
rem Start the FoE Alerting control panel (Windows). Double-click this file.
rem
rem No install step on purpose: the alerter imports nothing outside the standard library, so
rem all this does is point PYTHONPATH at src\ and run the module. Any argument you pass is
rem handed to `bap-alert ui` - e.g.  foe-alerting.bat --port 9000
rem
rem See docs\FOE_ALERTING_SETUP.md.

setlocal
cd /d "%~dp0"

rem The py launcher ships with the python.org installer and picks the right version; plain
rem "python" is the fallback for installs that skipped it (Microsoft Store, conda).
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=py -3"

if not defined PY (
    python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY=python"
)

if not defined PY (
    echo.
    echo   Python 3.11 or newer is required and was not found.
    echo.
    echo   Install it from https://www.python.org/downloads/
    echo   During setup, tick "Add python.exe to PATH", then run this file again.
    echo.
    pause
    exit /b 1
)

set "MAPDATA=dataset\api_samples\map_data.volcano_archipelago.sample.json"
set "MAPARG="
if exist "%MAPDATA%" set "MAPARG=--map-data %MAPDATA%"

echo.
echo   Starting the FoE Alerting panel...
echo   The URL below contains an access token - treat it like a password.
echo   Close this window to stop the panel.
echo.

set "PYTHONPATH=src"
%PY% -m bap.alerting ui %MAPARG% %*

rem Keep the window open if it stopped because of an error, so the message stays readable.
if errorlevel 1 pause
endlocal

@echo off
REM ===================================================================
REM  Forge Assistant - RUN (step 2 of collecting)
REM  Opens the Forge Assistant app.
REM  Do start-chrome.bat FIRST and log into Forge, then run this.
REM  The app only takes screenshots - it never clicks or plays for you.
REM ===================================================================
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [X] Not installed yet. Double-click  install.bat  first.
    echo(
    pause
    exit /b 1
)

echo Starting the Forge Assistant...
echo (If this is your first time, set Browser mode to "External Chrome (CDP)"
echo  on the Worlds page - see the Quick Start PDF.)
echo(

".venv\Scripts\python.exe" -m bap.gui.gui_main --forge

REM If the app closed immediately, an error is printed above.
if errorlevel 1 (
    echo(
    echo The app exited with an error. Screenshot this window for Radek.
    pause
)
exit /b 0

@echo off
REM ===================================================================
REM  Forge Assistant - COLLECT FRAMES (optional check before Push)
REM  Shows how many province screens the app saved while you played,
REM  and copies them into the dataset folder so they can be sent.
REM  You do NOT have to run this - "5 - Push.bat" does the same copy
REM  automatically. Use this any time you just want to see your count.
REM  Read-only: it never plays the game and never deletes anything.
REM ===================================================================
setlocal
cd /d "%~dp0.."

if not exist ".venv\Scripts\python.exe" (
    echo [X] Not installed yet. Double-click  "1 - Install.bat"  first.
    echo(
    pause
    exit /b 1
)

echo(
echo === What you've collected so far ===
".venv\Scripts\python.exe" -m bap.forge.collect

echo(
echo === Copying frames into the dataset (ready to send) ===
".venv\Scripts\python.exe" -m bap.forge.collect --export

echo(
echo When you're ready to send them to Radek, double-click  "5 - Push.bat".
echo(
pause
exit /b 0

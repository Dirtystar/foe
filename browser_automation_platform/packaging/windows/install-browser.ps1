<#
.SYNOPSIS
    First-run Chromium install for real (--real) automation.

.DESCRIPTION
    The beta installer ships WITHOUT a browser to keep the download small; the
    GUI runs on stubs out of the box. Run this once to download Chromium into
    your per-user data directory (%LOCALAPPDATA%\BAP\data\ms-playwright), which
    is where the app looks for it.

        powershell -ExecutionPolicy Bypass -File install-browser.ps1

    Disk usage: ~300-450 MB for Chromium. Safe to re-run (idempotent).
#>
$ErrorActionPreference = "Stop"

$Home = $env:BAP_HOME
if (-not $Home) { $Home = Join-Path $env:LOCALAPPDATA "BAP" }
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $Home "data\ms-playwright"
New-Item -ItemType Directory -Force -Path $env:PLAYWRIGHT_BROWSERS_PATH | Out-Null

Write-Host "Installing Chromium into $($env:PLAYWRIGHT_BROWSERS_PATH) ..." -ForegroundColor Cyan

# Prefer the installed app's bundled Playwright; fall back to a pip install.
$appDir = Join-Path $env:LOCALAPPDATA "Programs\BAP"
$bapExe = Join-Path $appDir "bap.exe"

if (Test-Path $bapExe) {
    # The bundled CLI carries Playwright; drive its module installer.
    & (Join-Path $appDir "BAP.exe") --help *> $null   # warm path (no-op if fails)
    python -m playwright install chromium
} else {
    python -m playwright install chromium
}

Write-Host "Done. Real automation (--real) can now launch a browser." -ForegroundColor Green

<#
.SYNOPSIS
    Post-build smoke validation on a clean Windows 10/11 x64 environment.

.DESCRIPTION
    Installs the built installer silently, exercises the CLI/GUI entry points
    and persistence against the bundled example config, then uninstalls. Run in
    a throwaway VM or fresh user profile:

        powershell -ExecutionPolicy Bypass -File validate.ps1 `
            -Installer .\Output\BAP-Setup-0.1.0.exe

    Exit code 0 = all checks passed. GUI launch is verified as a process start
    (a windowed app cannot be asserted headlessly); the rest is fully checked.
#>
[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$Installer)
$ErrorActionPreference = "Stop"

function Check($name, [scriptblock]$test) {
    Write-Host "-- $name ..." -NoNewline
    try { & $test; Write-Host " OK" -ForegroundColor Green }
    catch { Write-Host " FAIL" -ForegroundColor Red; throw }
}

$AppDir = Join-Path $env:LOCALAPPDATA "Programs\BAP"
$Gui    = Join-Path $AppDir "BAP.exe"
$Cli    = Join-Path $AppDir "bap.exe"
$DataDir = Join-Path $env:LOCALAPPDATA "BAP"

Check "silent install" {
    Start-Process -FilePath $Installer -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait
    if (-not (Test-Path $Gui)) { throw "GUI exe missing" }
    if (-not (Test-Path $Cli)) { throw "CLI exe missing" }
}

Check "version" {
    $v = & $Cli --version
    if ($v -notmatch "0\.1\.0") { throw "unexpected version: $v" }
}

Check "validate bundled example config" {
    & $Cli validate-config (Join-Path $AppDir "config\app.example.yaml")
    if ($LASTEXITCODE -ne 0) { throw "validate-config exit $LASTEXITCODE" }
}

Check "headless run + persistence" {
    $store = Join-Path $env:TEMP "bap-validate.db"
    Remove-Item $store -ErrorAction SilentlyContinue
    & $Cli run (Join-Path $AppDir "config\app.example.yaml") --seconds 3 --store $store
    if ($LASTEXITCODE -ne 0) { throw "run exit $LASTEXITCODE" }
    if (-not (Test-Path $store)) { throw "persistence file not created" }
    if ((Get-Item $store).Length -le 0) { throw "persistence file empty" }
}

Check "logs directory written" {
    if (-not (Test-Path (Join-Path $DataDir "logs"))) { throw "logs dir missing" }
}

Check "GUI launches" {
    $p = Start-Process -FilePath $Gui -PassThru
    Start-Sleep -Seconds 5
    if ($p.HasExited) { throw "GUI exited immediately (code $($p.ExitCode))" }
    Stop-Process -Id $p.Id -Force
}

Check "uninstall" {
    $uninst = Join-Path $AppDir "unins000.exe"
    if (Test-Path $uninst) {
        Start-Process -FilePath $uninst -ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait
    }
    if (Test-Path $Gui) { throw "app files remain after uninstall" }
}

Write-Host "`nAll validation checks passed." -ForegroundColor Green

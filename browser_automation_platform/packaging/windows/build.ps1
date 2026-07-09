<#
.SYNOPSIS
    Build the Windows beta: PyInstaller bundle -> Inno Setup installer ->
    SHA256 checksum + version manifest.

.DESCRIPTION
    Run on Windows 10/11 x64 with Python 3.11/3.12 and Inno Setup 6 installed
    (ISCC.exe on PATH). From the repository root:

        powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1

    Artifacts land in packaging\windows\Output\:
        BAP-Setup-<version>.exe
        BAP-Setup-<version>.exe.sha256
        version.txt
#>
[CmdletBinding()]
param(
    [switch]$SkipVenv,
    [switch]$SkipInstaller
)
$ErrorActionPreference = "Stop"

$Here    = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root    = Resolve-Path (Join-Path $Here "..\..")
$Venv    = Join-Path $Root ".buildvenv"
$Output  = Join-Path $Here "Output"
$Version = "0.1.0"

Push-Location $Root
try {
    # 1. Isolated build environment with the app + GUI/vision + PyInstaller.
    if (-not $SkipVenv) {
        Write-Host "==> Creating build venv" -ForegroundColor Cyan
        python -m venv $Venv
        & "$Venv\Scripts\python.exe" -m pip install --upgrade pip
        & "$Venv\Scripts\python.exe" -m pip install -e ".[gui,vision,monitoring]" pyinstaller
    }
    $Py = Join-Path $Venv "Scripts\python.exe"

    # 2. Confirm the packaged version matches the source of truth.
    $srcVersion = & $Py -c "import bap; print(bap.__version__)"
    if ($srcVersion.Trim() -ne $Version) {
        throw "Version mismatch: build.ps1=$Version but bap.__version__=$srcVersion"
    }

    # 3. Freeze both executables into dist\BAP.
    Write-Host "==> Running PyInstaller" -ForegroundColor Cyan
    & $Py -m PyInstaller "packaging\windows\bap.spec" --noconfirm --clean
    if (-not (Test-Path "dist\BAP\BAP.exe")) { throw "PyInstaller did not produce dist\BAP\BAP.exe" }

    # 4. Wrap dist\BAP into an installer (unless skipped).
    New-Item -ItemType Directory -Force -Path $Output | Out-Null
    if (-not $SkipInstaller) {
        Write-Host "==> Building installer with Inno Setup" -ForegroundColor Cyan
        $iscc = Get-Command ISCC.exe -ErrorAction SilentlyContinue
        if (-not $iscc) { throw "ISCC.exe (Inno Setup 6) not found on PATH." }
        & $iscc.Source "packaging\windows\bap-setup.iss"
    }

    # 5. Release artifacts: checksum + version manifest.
    $installer = Join-Path $Output "BAP-Setup-$Version.exe"
    if (Test-Path $installer) {
        Write-Host "==> Writing checksum + version manifest" -ForegroundColor Cyan
        $hash = (Get-FileHash -Algorithm SHA256 $installer).Hash.ToLower()
        "$hash  BAP-Setup-$Version.exe" | Out-File -Encoding ascii "$installer.sha256"

        @(
            "product      : Browser Automation Platform"
            "version      : $Version"
            "installer    : BAP-Setup-$Version.exe"
            "sha256       : $hash"
            "built_utc    : $((Get-Date).ToUniversalTime().ToString('u'))"
            "target       : Windows 10/11 x64"
            "python_build : $srcVersion"
        ) | Out-File -Encoding ascii (Join-Path $Output "version.txt")

        Write-Host "==> Done. Artifacts in $Output" -ForegroundColor Green
        Write-Host "    SHA256: $hash"
    } else {
        Write-Warning "Installer not found at $installer (did Inno Setup run?)"
    }
}
finally {
    Pop-Location
}

# Builds dist\DeltaSuite.exe (single file, no console).
# Usage:  .\build_exe.ps1                      -> uses the venv in $env:USERPROFILE\.venvs\miohub
#         .\build_exe.ps1 -Python C:\path\python.exe
param(
    [string]$Python = "$env:USERPROFILE\.venvs\miohub\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path $Python)) {
    Write-Host "Creating the venv in $(Split-Path (Split-Path $Python))..."
    py -3.11 -m venv (Split-Path (Split-Path $Python))
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r requirements.txt pyinstaller
}

& $Python tools\make_icon.py
# work folder outside OneDrive: thousands of temporary files
& $Python -m PyInstaller DeltaSuite.spec --noconfirm --clean `
    --workpath "$env:LOCALAPPDATA\DeltaSuite\build" --distpath dist
Write-Host "Done: $PSScriptRoot\dist\DeltaSuite.exe"

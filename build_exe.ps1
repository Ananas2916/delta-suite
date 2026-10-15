# Compila dist\DeltaSuite.exe (file unico, senza console).
# Uso:  .\build_exe.ps1                      -> usa il venv in $env:USERPROFILE\.venvs\miohub
#       .\build_exe.ps1 -Python C:\percorso\python.exe
param(
    [string]$Python = "$env:USERPROFILE\.venvs\miohub\Scripts\python.exe"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path $Python)) {
    Write-Host "Creo il venv in $(Split-Path (Split-Path $Python))..."
    py -3.11 -m venv (Split-Path (Split-Path $Python))
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r requirements.txt pyinstaller
}

& $Python tools\make_icon.py
# cartella di lavoro fuori da OneDrive: sono migliaia di file temporanei
& $Python -m PyInstaller DeltaSuite.spec --noconfirm --clean `
    --workpath "$env:LOCALAPPDATA\DeltaSuite\build" --distpath dist
Write-Host "Fatto: $PSScriptRoot\dist\DeltaSuite.exe"

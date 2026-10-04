# Prepara o ambiente de desenvolvimento do JULIUS no Windows (sem precisar de administrador).
# Uso: powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
# O venv fica FORA da pasta do projeto: pastas sincronizadas (OneDrive) corrompem venvs
$venv = Join-Path $env:USERPROFILE ".venvs\julius"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) { throw "Instale o Python 3.12+ (python.org)." }
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) { throw "Instale o Node.js LTS (nodejs.org) e reabra o terminal." }

if (-not (Test-Path "$venv\Scripts\python.exe")) { python -m venv $venv }
& "$venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r "$root\backend\requirements-dev.txt"

if (-not (Test-Path "$root\backend\.env")) { Copy-Item "$root\backend\.env.example" "$root\backend\.env" }

Push-Location "$root\backend"; & "$venv\Scripts\alembic.exe" upgrade head; Pop-Location
Push-Location "$root\frontend"; npm install --no-fund --no-audit; Pop-Location

Write-Host "`nPronto. Para usar: powershell -File scripts\start.ps1  (abre em http://127.0.0.1:8010)" -ForegroundColor Green

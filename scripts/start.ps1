# Compila o app e inicia o JULIUS em http://127.0.0.1:8010 (uso diário no PC).
# Para desenvolvimento com recarga automática use scripts\dev.ps1.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$venv = Join-Path $env:USERPROFILE ".venvs\julius"

Push-Location "$root\frontend"; npx vite build; Pop-Location
Push-Location "$root\backend"
& "$venv\Scripts\alembic.exe" upgrade head
Start-Process "http://127.0.0.1:8010"
& "$venv\Scripts\uvicorn.exe" app.main:app --host 127.0.0.1 --port 8010
Pop-Location

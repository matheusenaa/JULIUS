# Desenvolvimento: API com recarga automática (porta 8010) + Vite (porta 5173, com proxy para a API).
$root = Split-Path $PSScriptRoot -Parent
$venv = Join-Path $env:USERPROFILE ".venvs\julius"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root\backend'; & '$venv\Scripts\uvicorn.exe' app.main:app --reload --port 8010"
Set-Location "$root\frontend"
npx vite

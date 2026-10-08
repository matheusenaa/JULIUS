# Igual ao start.ps1, mas escuta em TODAS as interfaces: outro computador/celular
# da mesma rede abre http://<IP-deste-PC>:8010 e usa a mesma conta e os mesmos dados.
# Uso: powershell -ExecutionPolicy Bypass -File scripts\start-lan.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
$venv = Join-Path $env:USERPROFILE ".venvs\julius"

Push-Location "$root\frontend"; npx vite build; Pop-Location
Push-Location "$root\backend"
& "$venv\Scripts\alembic.exe" upgrade head

$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -ExpandProperty IPAddress
Write-Host "`nJULIUS neste PC:      http://127.0.0.1:8010" -ForegroundColor Green
foreach ($ip in $ips) { Write-Host "Outros aparelhos:     http://${ip}:8010" -ForegroundColor Green }
Write-Host "Mesma conta = mesmos dados em qualquer aparelho da rede.`n"

Start-Process "http://127.0.0.1:8010"
& "$venv\Scripts\uvicorn.exe" app.main:app --host 0.0.0.0 --port 8010
Pop-Location

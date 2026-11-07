# carga_supervisor.ps1 — Mantiene viva la corrida de la S4 sin intervención humana.
# Si carga.py se cae, espera 60 s, anota el reinicio en la bitácora y lo relanza
# (carga.py reanuda solo donde iba). Termina cuando la cola queda completa.
#
# Uso (desde la carpeta del proyecto):
#   powershell -ExecutionPolicy Bypass -File scripts\carga_supervisor.ps1
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
$python = ".\.venv\Scripts\python.exe"
New-Item -ItemType Directory -Force -Path "bitacora" | Out-Null
$reinicios = 0
while ($true) {
    & $python scripts\carga.py @args
    $codigo = $LASTEXITCODE
    if ($codigo -eq 0 -or $codigo -eq 2) { break }   # 0 = cola completa · 2 = configuración mala
    $reinicios++
    $hora = (Get-Date).ToString("yyyy-MM-ddTHH:mm:sszzz")
    $evento = '{"hora": "' + $hora + '", "tipo": "reinicio_automatico", "codigo_salida": ' + $codigo + ', "reinicio": ' + $reinicios + '}'
    Add-Content -Path "bitacora\s4_eventos.jsonl" -Value $evento -Encoding utf8
    Write-Host "Reinicio automatico #$reinicios en 60 s (codigo $codigo)..."
    Start-Sleep -Seconds 60
}
Write-Host "Supervisor terminado (codigo $codigo)."

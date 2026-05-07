# Setup Windows Task Scheduler para backfill SOFA histórico cada 32H.
# Cap 1500 calls/sesión. Idempotente. Continúa donde quedó.
#
# Uso:
#   PS> .\scripts\schedule_sofa_backfill_setup.ps1                # crea task
#   PS> .\scripts\schedule_sofa_backfill_setup.ps1 -Remove        # remueve task
#
# Logs: scrape_sofa_backfill_logs/sofa_backfill_<timestamp>.log

param(
    [switch]$Remove
)

$TaskName = "Adepor_SOFA_Backfill_Historico"
$ProyectoPath = "C:\Users\map12\Desktop\Proyecto_Adepor"
$LogsDir = Join-Path $ProyectoPath "scrape_sofa_backfill_logs"
$ScriptPath = Join-Path $ProyectoPath "scripts\scrape_sofa_backfill_historico.py"
$WrapperPath = Join-Path $ProyectoPath "scripts\schedule_sofa_backfill_run.ps1"

if ($Remove) {
    Write-Host "Removing scheduled task..."
    schtasks /Delete /TN $TaskName /F
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Task removed: $TaskName"
    }
    exit
}

# Crear directorio logs
if (-not (Test-Path $LogsDir)) {
    New-Item -ItemType Directory -Path $LogsDir | Out-Null
    Write-Host "Created logs dir: $LogsDir"
}

# Crear wrapper PowerShell que:
#   1. Ejecuta py con cap 1500
#   2. Redirige logs a $LogsDir
#   3. Self-reschedules el task para 32H después (asegura 32H exacto vs schtasks /MO limit)
$WrapperContent = @"
# Auto-generated wrapper. NO editar.
`$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
`$logFile = Join-Path '$LogsDir' "sofa_backfill_`$ts.log"
Set-Location '$ProyectoPath'
& py '$ScriptPath' --cap 1500 *>&1 | Tee-Object -FilePath `$logFile

# Self-reschedule: próximo run en +32 horas exacto
`$NextRun = (Get-Date).AddHours(32)
`$NextDate = `$NextRun.ToString('dd/MM/yyyy')
`$NextTime = `$NextRun.ToString('HH:mm')
schtasks /Create /TN '$TaskName' /TR "powershell -ExecutionPolicy Bypass -File `"$WrapperPath`"" /SC ONCE /SD `$NextDate /ST `$NextTime /F /RL LIMITED 2>&1 | Add-Content -Path `$logFile
"@

Set-Content -Path $WrapperPath -Value $WrapperContent -Encoding UTF8
Write-Host "Wrapper creado: $WrapperPath"

# Borrar task previa si existe
schtasks /Query /TN $TaskName 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-Host "Removing previous task..."
    schtasks /Delete /TN $TaskName /F
}

# Schedule: cada 32 horas = 1920 minutos.
# Inicio: now + 5 min (no inmediato).
$Start = (Get-Date).AddMinutes(5).ToString("HH:mm")

# Initial schedule: ONCE en +5 min. El wrapper se auto-reschedula a +32H después de cada run.
$StartDate = (Get-Date).AddMinutes(5).ToString("dd/MM/yyyy")
$StartTime = (Get-Date).AddMinutes(5).ToString("HH:mm")

schtasks /Create `
    /TN $TaskName `
    /TR "powershell -ExecutionPolicy Bypass -File `"$WrapperPath`"" `
    /SC ONCE `
    /SD $StartDate `
    /ST $StartTime `
    /F `
    /RL LIMITED

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Task creada: $TaskName"
    Write-Host "  Trigger: cada 1920 min (32H), iniciando $Start"
    Write-Host "  Wrapper: $WrapperPath"
    Write-Host "  Cap por sesion: 1500 calls (~370 partidos)"
    Write-Host "  Backfill total estimado: 13,404 partidos / 36 sesiones = ~48 dias"
    Write-Host "  Logs: $LogsDir"
    Write-Host ""
    Write-Host "Verificar: schtasks /Query /TN $TaskName /V /FO LIST"
    Write-Host "Remover:   .\scripts\schedule_sofa_backfill_setup.ps1 -Remove"
} else {
    Write-Host "FAIL al crear task. Verificar permisos."
    exit 1
}

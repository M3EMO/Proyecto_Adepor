# Setup Windows Task Scheduler para backfill SOFA histórico cada 32H.
# Cap 1000 calls/sesión. Idempotente. Continúa donde quedó.
#
# Uso:
#   PS> .\scripts\schedule_sofa_backfill_setup.ps1                # crea task
#   PS> .\scripts\schedule_sofa_backfill_setup.ps1 -Remove        # remueve task
#
# Logs: scrape_sofa_backfill_logs/sofa_backfill_<timestamp>.log

param(
    [switch]$Remove,
    [string]$StartHour
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
#   1. Ejecuta py con cap 1000 (try/catch para garantizar reschedule)
#   2. Redirige logs a $LogsDir
#   3. Self-reschedules INCLUSO si py falla (try/finally) — fix bug 2026-05-08:
#      el wrapper anterior tenía quotes anidadas mal escapadas en /TR
#      causando que schtasks fallara silenciosamente y dejara N/A próxima ejec.
#   4. Como WrapperPath no tiene espacios, /TR usa path sin quotes inner
$WrapperContent = @"
# Auto-generated wrapper. NO editar.
`$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
`$logFile = Join-Path '$LogsDir' "sofa_backfill_`$ts.log"

try {
    Set-Location '$ProyectoPath'
    & 'C:\Users\map12\AppData\Local\Python\bin\python.exe' '$ScriptPath' --cap 1000 *>&1 | Tee-Object -FilePath `$logFile
} catch {
    "[ERROR] py crashed: `$_" | Out-File -FilePath `$logFile -Append
} finally {
    # SIEMPRE re-armar próximo run, incluso si py crasheó
    `$NextRun = (Get-Date).AddHours(32)
    `$NextDate = `$NextRun.ToString('dd/MM/yyyy')
    `$NextTime = `$NextRun.ToString('HH:mm')
    `$tr = "powershell -ExecutionPolicy Bypass -File $WrapperPath"
    `$rescheduleOutput = schtasks /Create /TN '$TaskName' /TR `$tr /SC ONCE /SD `$NextDate /ST `$NextTime /F /RL LIMITED 2>&1
    "[RESCHEDULE] Next run: `$NextDate `$NextTime" | Out-File -FilePath `$logFile -Append
    `$rescheduleOutput | Out-File -FilePath `$logFile -Append
}
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

# Initial schedule: mañana 06:00 si no se especifica $StartHour.
# El wrapper se auto-reschedula a +32H después de cada run (con bug fix
# 2026-05-08: ya no falla silenciosamente por quotes anidadas).
if (-not $StartHour) { $StartHour = '06:00' }
$StartDate = (Get-Date).AddDays(1).ToString("dd/MM/yyyy")
$StartTime = $StartHour
$tr = "powershell -ExecutionPolicy Bypass -File $WrapperPath"

schtasks /Create `
    /TN $TaskName `
    /TR $tr `
    /SC ONCE `
    /SD $StartDate `
    /ST $StartTime `
    /F `
    /RL LIMITED

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "Task creada: $TaskName"
    Write-Host "  Primera ejecucion: $StartDate $StartTime"
    Write-Host "  Auto-reschedule: +32H exacto tras cada run (try/finally)"
    Write-Host "  Rotacion horaria: 06:00 -> 14:00 -> 22:00 -> 06:00 ..."
    Write-Host "  Wrapper: $WrapperPath"
    Write-Host "  Cap por sesion: 1000 calls (~250 partidos)"
    Write-Host "  Universo total: 24,069 partidos (ligas + copas)"
    Write-Host "  ETA backfill: ~80 sesiones / ~107 dias"
    Write-Host "  Logs: $LogsDir"
    Write-Host ""
    Write-Host "Verificar: powershell schtasks /Query /TN $TaskName /V /FO LIST"
    Write-Host "Remover:   .\scripts\schedule_sofa_backfill_setup.ps1 -Remove"
} else {
    Write-Host "FAIL al crear task. Verificar permisos."
    exit 1
}

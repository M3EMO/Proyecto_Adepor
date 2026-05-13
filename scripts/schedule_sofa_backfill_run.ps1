# Auto-generated wrapper. NO editar.
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$logFile = Join-Path 'C:\Users\map12\Desktop\Proyecto_Adepor\scrape_sofa_backfill_logs' "sofa_backfill_$ts.log"

try {
    Set-Location 'C:\Users\map12\Desktop\Proyecto_Adepor'
    & 'C:\Users\map12\AppData\Local\Python\bin\python.exe' 'C:\Users\map12\Desktop\Proyecto_Adepor\scripts\scrape_sofa_backfill_historico.py' --cap 1000 *>&1 | Tee-Object -FilePath $logFile
} catch {
    "[ERROR] py crashed: $_" | Out-File -FilePath $logFile -Append
} finally {
    # SIEMPRE re-armar prÃ³ximo run, incluso si py crasheÃ³
    $NextRun = (Get-Date).AddHours(32)
    $NextDate = $NextRun.ToString('dd/MM/yyyy')
    $NextTime = $NextRun.ToString('HH:mm')
    $tr = "powershell -ExecutionPolicy Bypass -File C:\Users\map12\Desktop\Proyecto_Adepor\scripts\schedule_sofa_backfill_run.ps1"
    $rescheduleOutput = schtasks /Create /TN 'Adepor_SOFA_Backfill_Historico' /TR $tr /SC ONCE /SD $NextDate /ST $NextTime /F /RL LIMITED 2>&1
    "[RESCHEDULE] Next run: $NextDate $NextTime" | Out-File -FilePath $logFile -Append
    $rescheduleOutput | Out-File -FilePath $logFile -Append
}

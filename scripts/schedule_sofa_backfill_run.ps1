# Auto-generated wrapper. NO editar.
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$logFile = Join-Path 'C:\Users\map12\Desktop\Proyecto_Adepor\scrape_sofa_backfill_logs' "sofa_backfill_$ts.log"
Set-Location 'C:\Users\map12\Desktop\Proyecto_Adepor'
& py 'C:\Users\map12\Desktop\Proyecto_Adepor\scripts\scrape_sofa_backfill_historico.py' --cap 1500 *>&1 | Tee-Object -FilePath $logFile

# Self-reschedule: prÃ³ximo run en +32 horas exacto
$NextRun = (Get-Date).AddHours(32)
$NextDate = $NextRun.ToString('dd/MM/yyyy')
$NextTime = $NextRun.ToString('HH:mm')
schtasks /Create /TN 'Adepor_SOFA_Backfill_Historico' /TR "powershell -ExecutionPolicy Bypass -File "C:\Users\map12\Desktop\Proyecto_Adepor\scripts\schedule_sofa_backfill_run.ps1"" /SC ONCE /SD $NextDate /ST $NextTime /F /RL LIMITED 2>&1 | Add-Content -Path $logFile

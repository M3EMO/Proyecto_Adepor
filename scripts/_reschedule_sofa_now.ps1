# Temporal: reagendar Adepor_SOFA_Backfill_Historico a +2 min para test post-fix
$NextRun = (Get-Date).AddMinutes(2)
$NextDate = $NextRun.ToString('dd/MM/yyyy')
$NextTime = $NextRun.ToString('HH:mm')
$tr = "powershell -ExecutionPolicy Bypass -File C:\Users\map12\Desktop\Proyecto_Adepor\scripts\schedule_sofa_backfill_run.ps1"
schtasks /Create /TN 'Adepor_SOFA_Backfill_Historico' /TR $tr /SC ONCE /SD $NextDate /ST $NextTime /F /RL LIMITED
Write-Host "Rescheduled: $NextDate $NextTime"

$TaskName = "WSL-expense_project2-autostart"
$WslArg = "-d Ubuntu-24.04 -- /bin/sleep infinity"
$action = New-ScheduledTaskAction -Execute "wsl.exe" -Argument $WslArg
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$noLimit = [System.TimeSpan]::Zero
$interval = New-TimeSpan -Minutes 1
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit $noLimit -RestartCount 3 -RestartInterval $interval -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
Write-Host "Registered: $TaskName"

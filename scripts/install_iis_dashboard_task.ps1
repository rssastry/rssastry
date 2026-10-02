param(
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$TaskName = 'StockAnalysis IIS Dashboard'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $RepoRoot 'scripts\run_iis_dashboard.ps1'
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$UserId = "$env:USERDOMAIN\$env:USERNAME"

if ($Remove) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed $TaskName."
    return
}

$Action = New-ScheduledTaskAction -Execute $PowerShell -Argument `
    ("-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"{0}`"" -f $Runner)
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings -Description `
    'Starts the StockAnalysis Streamlit dashboard for the local IIS reverse proxy.' -Force | Out-Null

Write-Host "Registered $TaskName for $UserId at logon."
Write-Host "Start it now with: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Logs: $RepoRoot\logs\iis-dashboard.log"
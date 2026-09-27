# install_windows_scan_jobs.ps1 — register Windows Scheduled Tasks that run
# the StockAnalysis daily scans on NSE business days.
#
# Two tasks are created for the CURRENT logged-on user (no admin required):
#
#   "StockAnalysis Morning Scan"          Mon-Fri  15:45 IST  post-close scan
#                                            (price refresh + fundamentals +
#                                             screener + AI + Telegram alerts;
#                                             NSE holidays skipped by the app)
#   "StockAnalysis Fundamentals Capture"  Mon-Fri  08:30 IST  point-in-time
#                                            fundamental snapshots for the
#                                            whole NSE universe
#
# Both target scripts\run_scan_job.ps1, which resolves the .venv Python, sets
# the working directory, and writes dated logs to <repo>\logs\.
#
# Trigger times are entered in IST and converted to the local machine's time
# zone automatically, so the tasks always fire at the intended IST wall clock
# even if this PC is not on India Standard Time.
#
# Usage (from the repo root, any shell):
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_windows_scan_jobs.ps1
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_windows_scan_jobs.ps1 -MorningTime 15:45 -SnapshotTime 08:30
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install_windows_scan_jobs.ps1 -Remove
#
# Note: tasks run with interactive logon (they run while you are logged in),
# which avoids storing a password. To run when logged off, use Task Scheduler
# (task -> Properties -> General -> "Run whether user is logged on or not"),
# or the app can also run unattended via GitHub Actions (daily-scan.yml).
param(
    [string]$MorningTime  = '15:45',   # IST wall clock for the morning scan
    [string]$SnapshotTime = '08:30',   # IST wall clock for the fundamentals job
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'

$RepoRoot   = Split-Path -Parent $PSScriptRoot
$Runner     = Join-Path $RepoRoot 'scripts\run_scan_job.ps1'
$PowerShell = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$Principal  = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$Settings   = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 5) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$WeekDays   = 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'

# Convert an IST HH:mm to the local machine's HH:mm so triggers stay pinned
# to IST even when the box runs in another time zone.
function ConvertFrom-IST([string]$Time) {
    $h, $m = $Time.Split(':') | ForEach-Object { [int]$_ }
    $ist = [DateTimeOffset]::new(2026, 1, 1, $h, $m, 0, [TimeSpan]::FromHours(5.5))
    return $ist.ToLocalTime().ToString('HH:mm')
}

function New-ScanTask([string]$Name, [string]$Job, [string]$IstTime, [string]$Desc) {
    $Local   = ConvertFrom-IST $IstTime
    $Action  = New-ScheduledTaskAction -Execute $PowerShell -Argument `
        ("-NoProfile -ExecutionPolicy Bypass -File `"{0}`" -Job {1}" -f $Runner, $Job)
    $Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $WeekDays -At $Local
    $Task    = New-ScheduledTask -Action $Action -Trigger $Trigger `
        -Settings $Settings -Principal $Principal -Description $Desc
    Register-ScheduledTask -TaskName $Name -InputObject $Task -Force
    Write-Host ("[registered] {0} | {1} at {2} local ({3} IST), job={4}" -f `
        $Name, 'Mon-Fri', $Local, $IstTime, $Job)
}

if ($Remove) {
    foreach ($Name in @('StockAnalysis Morning Scan', 'StockAnalysis Fundamentals Capture')) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "[removed] $Name"
    }
    Write-Host 'Done.'
    return
}

New-ScanTask 'StockAnalysis Morning Scan' 'morning' $MorningTime `
    'StockAnalysis: post-close market scan 15:45 IST Mon-Fri (prices + fundamentals + screener + AI + Telegram). NSE holidays skipped by the app.'
New-ScanTask 'StockAnalysis Fundamentals Capture' 'snapshot' $SnapshotTime `
    'StockAnalysis: point-in-time fundamental snapshots for the NSE universe, 08:30 IST Mon-Fri (pre-market freshness).'

Write-Host ''
Write-Host 'Registered for current user only (runs while you are logged on).'
Write-Host 'Verify with:  Get-ScheduledTask -TaskName "StockAnalysis*" | Select-Object TaskName, State'
Write-Host 'Logs:         <repo>\logs\<job>-<yyyy-MM-dd>.log'

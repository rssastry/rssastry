# run_scan_job.ps1 — run one StockAnalysis scan job under the project .venv
# and append all output to a dated log file. The process exit code (Python's)
# is propagated so Task Scheduler can flag failures.
#
# This script is the action target of the Windows Scheduled Tasks installed by
# scripts/install_windows_scan_jobs.ps1. It is also safe to run by hand:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_scan_job.ps1 -Job morning
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_scan_job.ps1 -Job snapshot
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_scan_job.ps1 -Job selfcheck
#
# Jobs:
#    morning   -> .venv\Scripts\python.exe schedular.py morning
#                 Post-close market scan: refresh price CSVs, capture
#                 fundamental snapshots, run the screener + AI second opinion,
#                 send Telegram buy/summary alerts. Skips weekends and NSE
#                 holidays internally (is_market_day).
#    snapshot  -> .venv\Scripts\python.exe run.py snapshot
#                 Point-in-time fundamental snapshot capture for the whole NSE
#                 universe (also part of 'morning'; run early if you want
#                 fresher numbers available through the market day).
#    selfcheck -> imports core deps and prints the interpreter path; used to
#                 verify the task plumbing (Python, working dir, logging).
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('morning', 'snapshot', 'selfcheck')]
    [string]$Job,
    [string]$LogDir = ''
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot

# Prefer the project virtualenv; fall back to any python.exe on PATH.
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) {
    $Python = (Get-Command python -ErrorAction SilentlyContinue).Source
}
if (-not $Python -or -not (Test-Path $Python)) {
    Write-Error 'No usable Python found (looked for .venv\Scripts\python.exe and PATH).'
}

if (-not $LogDir) { $LogDir = Join-Path $RepoRoot 'logs' }
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir ("{0}-{1}.log" -f $Job, (Get-Date).ToString('yyyy-MM-dd'))

function Append-Log([string]$Line) {
    Add-Content -Path $LogFile -Value $Line -Encoding UTF8
}

# Run a venv command and stream every line (stdout + stderr) into the UTF-8
# log. PS 5.1's plain *>> would write the native output as UTF-16; this keeps
# the file uniformly readable.
function Invoke-Logged([object[]]$PyArgs) {
    & $Python @PyArgs 2>&1 | ForEach-Object {
        $text = [string]$_
        if ($text.Length) { Append-Log ($text.TrimEnd("`r", "`n")) }
    }
}

Append-Log ("[{0}] {1} START pid={2}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $Job, $PID)

Push-Location $RepoRoot
try {
    switch ($Job) {
        'morning'   { Invoke-Logged @('schedular.py', 'morning') }
        'snapshot'  { Invoke-Logged @('run.py', 'snapshot') }
        'selfcheck' { Invoke-Logged @('-c', "import sys; import yfinance, pandas, streamlit, numpy; print('selfcheck ok |', sys.executable)") }
    }
    $ExitCode = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE } else { 1 }
}
catch {
    Append-Log ("[{0}] {1} ERROR {2}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $Job, $_.Exception.Message)
    $ExitCode = 1
}
finally {
    Pop-Location
}

Append-Log ("[{0}] {1} END exit={2}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $Job, $ExitCode)
exit $ExitCode

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepoRoot '.venv\Scripts\python.exe'

if (-not (Test-Path $Python)) {
    throw "Project Python was not found at $Python. Create the .venv and install requirements.txt first."
}

$env:SA_DATA_DIR = $RepoRoot
$LogDir = Join-Path $RepoRoot 'logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir 'iis-dashboard.log'

Push-Location $RepoRoot
try {
    Add-Content -Path $LogFile -Value ("[{0}] Dashboard starting; data root={1}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $env:SA_DATA_DIR) -Encoding UTF8
    $PreviousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & $Python -m streamlit run dashboard.py `
        --server.address 127.0.0.1 `
        --server.port 8501 `
        --server.headless true `
        --browser.gatherUsageStats false 2>&1 | ForEach-Object {
            $text = [string]$_
            if ($text.Length) {
                Add-Content -Path $LogFile -Value $text -Encoding UTF8
            }
        }
    $ExitCode = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE } else { 1 }
    $ErrorActionPreference = $PreviousErrorActionPreference
}
finally {
    Pop-Location
}

Add-Content -Path $LogFile -Value ("[{0}] Dashboard stopped; exit={1}" -f (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'), $ExitCode) -Encoding UTF8
exit $ExitCode
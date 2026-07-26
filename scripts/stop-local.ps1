param()

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $repoRoot ".tmp\local-dev\pids.json"

if (-not (Test-Path $pidFile)) {
    Write-Host "No PID file found at $pidFile"
    exit 0
}

$state = Get-Content $pidFile -Raw | ConvertFrom-Json

foreach ($processInfo in $state.processes) {
    $serviceProcessId = [int]$processInfo.pid
    try {
        $null = Get-Process -Id $serviceProcessId -ErrorAction Stop
        taskkill /PID $serviceProcessId /T /F | Out-Null
        Write-Host ("Stopped {0} (PID tree rooted at {1})" -f $processInfo.name, $serviceProcessId)
    }
    catch {
        Write-Host ("Already stopped or missing: {0} (PID {1})" -f $processInfo.name, $serviceProcessId)
    }
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "Cleared PID file."

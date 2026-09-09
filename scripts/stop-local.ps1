[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$pidFile = Join-Path $repoRoot ".tmp\local-dev\pids.json"

function Get-ListeningProcessId {
    param([int]$Port)

    foreach ($line in (& netstat.exe -ano -p tcp)) {
        if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            return [int]$Matches[1]
        }
    }
    return $null
}

function Stop-ProcessTree {
    param([int]$RootProcessId)

    if (-not (Get-Process -Id $RootProcessId -ErrorAction SilentlyContinue)) {
        return
    }
    $killer = Start-Process -FilePath "taskkill.exe" `
        -ArgumentList @("/PID", [string]$RootProcessId, "/T", "/F") `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($killer.ExitCode -ne 0) {
        Stop-Process -Id $RootProcessId -Force -ErrorAction SilentlyContinue
    }
}

if (-not (Test-Path $pidFile)) {
    Write-Host "No PID file found at $pidFile"
    exit 0
}

$state = try {
    Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
}
catch {
    throw "Could not read PID file '$pidFile': $($_.Exception.Message)"
}

$processes = @($state.processes)
[array]::Reverse($processes)
$failed = @()
foreach ($processInfo in $processes) {
    $serviceProcessId = [int]$processInfo.pid
    $runningProcess = Get-Process -Id $serviceProcessId -ErrorAction SilentlyContinue
    if ($runningProcess) {
        if ($processInfo.process_started_at_utc) {
            $recordedStartTime = [DateTimeOffset]::Parse([string]$processInfo.process_started_at_utc).UtcDateTime
            $actualStartTime = $runningProcess.StartTime.ToUniversalTime()
            if ([Math]::Abs(($actualStartTime - $recordedStartTime).TotalSeconds) -gt 2) {
                Write-Warning ("Skipped {0}: PID {1} now belongs to a different process." -f $processInfo.name, $serviceProcessId)
                $failed += $processInfo
                continue
            }
        }
        Stop-ProcessTree -RootProcessId $serviceProcessId
    }

    Start-Sleep -Milliseconds 150

    # uv/npm wrappers can exit before their Uvicorn/Vite child. Resolve the
    # current port owner at shutdown instead of trusting only the startup PID.
    $currentListenerProcessId = $null
    $hadListener = $false
    if ($processInfo.port) {
        $currentListenerProcessId = Get-ListeningProcessId -Port ([int]$processInfo.port)
        if ($currentListenerProcessId) {
            $hadListener = $true
            Stop-ProcessTree -RootProcessId $currentListenerProcessId
        }
    }

    $deadline = (Get-Date).AddSeconds(3)
    do {
        Start-Sleep -Milliseconds 100
        $rootStillRunning = Get-Process -Id $serviceProcessId -ErrorAction SilentlyContinue
        $currentListenerProcessId = if ($processInfo.port) { Get-ListeningProcessId -Port ([int]$processInfo.port) } else { $null }
    } while (($rootStillRunning -or $currentListenerProcessId) -and (Get-Date) -lt $deadline)

    if ($rootStillRunning -or $currentListenerProcessId) {
        Write-Warning ("Could not fully stop {0}; root PID {1}, port {2}." -f $processInfo.name, $serviceProcessId, $processInfo.port)
        $failed += $processInfo
        continue
    }

    if ($runningProcess -or $hadListener) {
        Write-Host ("Stopped {0} (PID tree rooted at {1})" -f $processInfo.name, $serviceProcessId)
    }
    elseif ($processInfo.port) {
        Write-Host ("Stopped or already missing: {0}; port {1} is released." -f $processInfo.name, $processInfo.port)
    }
    else {
        Write-Host ("Already stopped or missing: {0} (PID {1})" -f $processInfo.name, $serviceProcessId)
    }
}

if ($failed.Count -gt 0) {
    $state.processes = $failed
    $state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $pidFile -Encoding UTF8
    throw "Some services could not be stopped. Their entries were kept in $pidFile"
}

Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
Write-Host "Cleared PID file."

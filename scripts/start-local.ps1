[CmdletBinding()]
param(
    [switch]$SkipBridge,
    [switch]$SkipApi,
    [switch]$SkipWorker,
    [switch]$SkipWeb,
    [switch]$InlineMode,
    [switch]$ArqMode,
    [switch]$StubAgent,
    [switch]$LangGraph,
    [int]$BridgePort = 8085,
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $repoRoot ".tmp\local-dev"
$logDir = Join-Path $runDir "logs"
$pidFile = Join-Path $runDir "pids.json"

if ($env:CODEX_SANDBOX_NETWORK_DISABLED -eq "1") {
    throw "Network access is disabled in this Codex sandbox. Open a regular PowerShell window, change to '$repoRoot', and run .\start.cmd there."
}

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

# Keep npm's transient cache on the project drive. The user profile may live
# on a small system disk, and a full profile cache should not prevent the web
# service from starting.
if (-not $env:NPM_CONFIG_CACHE) {
    $env:NPM_CONFIG_CACHE = Join-Path $runDir "npm-cache"
}
New-Item -ItemType Directory -Force -Path $env:NPM_CONFIG_CACHE | Out-Null

if ($InlineMode -and $ArqMode) {
    throw "-InlineMode and -ArqMode cannot be used together."
}
if ($StubAgent -and $LangGraph) {
    throw "-StubAgent and -LangGraph cannot be used together."
}

$selectedPorts = @()
if (-not $SkipBridge) { $selectedPorts += $BridgePort }
if (-not $SkipApi) { $selectedPorts += $ApiPort }
if (-not $SkipWeb) { $selectedPorts += $WebPort }
if ($selectedPorts.Count -eq 0) {
    throw "No service was selected. Remove at least one -Skip* option."
}
foreach ($port in $selectedPorts) {
    if ($port -lt 1 -or $port -gt 65535) {
        throw "Invalid port: $port"
    }
}
if (($selectedPorts | Sort-Object -Unique).Count -ne $selectedPorts.Count) {
    throw "Bridge, API, and web ports must be different."
}

if (Test-Path $pidFile) {
    try {
        $oldState = Get-Content -LiteralPath $pidFile -Raw | ConvertFrom-Json
        $activeEntries = @(@($oldState.processes) | Where-Object {
            (Get-Process -Id ([int]$_.pid) -ErrorAction SilentlyContinue) -or
            ($_.listener_pid -and (Get-Process -Id ([int]$_.listener_pid) -ErrorAction SilentlyContinue))
        })
        if ($activeEntries.Count -gt 0) {
            $activeSummary = ($activeEntries | ForEach-Object { "{0} (PID {1})" -f $_.name, $_.pid }) -join ", "
            throw "Local services are already running: $activeSummary. Run .\stop.cmd first."
        }
    }
    catch {
        if ($_.Exception.Message -like "Local services are already running:*") {
            throw
        }
        Write-Warning "Ignoring an unreadable stale PID file: $pidFile"
    }
    Remove-Item -LiteralPath $pidFile -Force
}

if ((-not $SkipBridge -or -not $SkipApi -or ($ArqMode -and -not $SkipWorker)) -and -not (Get-Command "uv" -ErrorAction SilentlyContinue)) {
    throw "The 'uv' command was not found. Install uv and make sure it is available on PATH."
}
if (-not $SkipWeb -and -not (Get-Command "npm" -ErrorAction SilentlyContinue)) {
    throw "The 'npm' command was not found. Install Node.js and make sure npm is available on PATH."
}

function Get-ListeningProcessId {
    param([int]$Port)

    foreach ($line in (& netstat.exe -ano -p tcp)) {
        if ($line -match "^\s*TCP\s+\S+:$Port\s+\S+\s+LISTENING\s+(\d+)\s*$") {
            return [int]$Matches[1]
        }
    }
    return $null
}

$portAssignments = @()
if (-not $SkipBridge) { $portAssignments += [pscustomobject]@{ Name = "GrokSearch bridge"; Port = $BridgePort } }
if (-not $SkipApi) { $portAssignments += [pscustomobject]@{ Name = "API"; Port = $ApiPort } }
if (-not $SkipWeb) { $portAssignments += [pscustomobject]@{ Name = "Web"; Port = $WebPort } }
foreach ($assignment in $portAssignments) {
    $ownerPid = Get-ListeningProcessId -Port $assignment.Port
    if ($ownerPid) {
        throw ("{0} port {1} is already in use by PID {2}." -f $assignment.Name, $assignment.Port, $ownerPid)
    }
}

function ConvertTo-CmdLiteral {
    param([string]$Value)
    return '"' + ($Value -replace '"', '""') + '"'
}

function Stop-ProcessTree {
    param(
        [int]$RootProcessId,
        [Nullable[int]]$ListenerProcessId = $null
    )

    if (Get-Process -Id $RootProcessId -ErrorAction SilentlyContinue) {
        $killer = Start-Process -FilePath "taskkill.exe" `
            -ArgumentList @("/PID", [string]$RootProcessId, "/T", "/F") `
            -WindowStyle Hidden `
            -Wait `
            -PassThru
        if ($killer.ExitCode -ne 0) {
            Stop-Process -Id $RootProcessId -Force -ErrorAction SilentlyContinue
            if ($ListenerProcessId) {
                Stop-Process -Id $ListenerProcessId.Value -Force -ErrorAction SilentlyContinue
            }
        }
    }
    elseif ($ListenerProcessId) {
        Stop-Process -Id $ListenerProcessId.Value -Force -ErrorAction SilentlyContinue
    }
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$Command,
        [hashtable]$Environment = @{},
        [string]$WorkingDirectory = $repoRoot,
        [int]$Port = 0
    )

    $runToken = Get-Date -Format "yyyyMMdd-HHmmss-fff"
    $logPath = Join-Path $logDir "$Name-$runToken.log"
    if (Test-Path $logPath) {
        Remove-Item -LiteralPath $logPath -Force -ErrorAction SilentlyContinue
    }

    $cmdSegments = @("cd /d " + (ConvertTo-CmdLiteral $WorkingDirectory))
    foreach ($key in $Environment.Keys) {
        $cmdSegments += 'set "' + $key + '=' + [string]$Environment[$key] + '"'
    }
    $cmdSegments += $Command + " >> " + (ConvertTo-CmdLiteral $logPath) + " 2>>&1"
    $cmdLine = $cmdSegments -join " && "

    $process = Start-Process -FilePath "cmd.exe" `
        -ArgumentList @("/d", "/c", $cmdLine) `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -PassThru

    $listenerPid = $null
    $deadline = (Get-Date).AddSeconds(30)
    do {
        Start-Sleep -Milliseconds 250
        $process.Refresh()
        if ($process.HasExited) {
            throw "Process $Name exited during startup. Check log: $logPath"
        }
        if ($Port -gt 0) {
            $listenerPid = Get-ListeningProcessId -Port $Port
            if ($listenerPid) { break }
        }
        else {
            break
        }
    } while ((Get-Date) -lt $deadline)

    if ($Port -gt 0 -and -not $listenerPid) {
        Stop-ProcessTree -RootProcessId $process.Id
        throw "Process $Name did not listen on port $Port within 30 seconds. Check log: $logPath"
    }

    return [pscustomobject]@{
        name = $Name
        pid = $process.Id
        process_started_at_utc = $process.StartTime.ToUniversalTime().ToString("o")
        listener_pid = $listenerPid
        port = if ($Port -gt 0) { $Port } else { $null }
        log = $logPath
        command = $Command
    }
}

function Stop-StartedProcesses {
    param([object[]]$Processes)

    $processList = @($Processes)
    [array]::Reverse($processList)
    foreach ($entry in $processList) {
        $listenerProcessId = if ($entry.listener_pid) { [Nullable[int]][int]$entry.listener_pid } else { $null }
        Stop-ProcessTree -RootProcessId ([int]$entry.pid) -ListenerProcessId $listenerProcessId
    }
}

$queueMode = if ($ArqMode) { "arq" } else { "inline" }
$uvEnv = @{ "UV_CACHE_DIR" = (Join-Path $repoRoot ".uv-cache") }
$sharedEnv = @{ "UV_CACHE_DIR" = $uvEnv["UV_CACHE_DIR"] }
if ($InlineMode -or -not $ArqMode) {
    $sharedEnv["TRAVELMIND_QUEUE_MODE"] = "inline"
}
if ($ArqMode) {
    $sharedEnv["TRAVELMIND_QUEUE_MODE"] = "arq"
    $sharedEnv["TRAVELMIND_REDIS_URL"] = "redis://127.0.0.1:6379/0"
}
if ($StubAgent -or -not $LangGraph) {
    $sharedEnv["TRAVELMIND_AGENT_PROVIDER"] = "stub"
}
if ($LangGraph) {
    $sharedEnv["TRAVELMIND_AGENT_PROVIDER"] = "langgraph"
}

$started = @()
$startWorker = -not $SkipWorker -and $ArqMode

try {
    if (-not $SkipBridge) {
        $started += Start-ManagedProcess `
            -Name "groksearch-bridge" `
            -Command "uv run --project apps/groksearch-bridge uvicorn travelmind_groksearch_bridge.main:app --host 127.0.0.1 --port $BridgePort" `
            -Environment $uvEnv `
            -Port $BridgePort
    }

    if (-not $SkipApi) {
        $started += Start-ManagedProcess `
            -Name "api" `
            -Command "uv run --project apps/api uvicorn travelmind_api.main:app --host 127.0.0.1 --port $ApiPort" `
            -Environment $sharedEnv `
            -Port $ApiPort
    }

    if ($startWorker) {
        $started += Start-ManagedProcess `
            -Name "worker" `
            -Command "uv run --project apps/worker python -m travelmind_worker.worker" `
            -Environment $sharedEnv
    }

    if (-not $SkipWeb) {
        # Keep browser API requests on the same origin as the page. Vite
        # proxies /api to FastAPI, so auth cookies also work when the page
        # is opened through either localhost or 127.0.0.1.
        $started += Start-ManagedProcess `
            -Name "web" `
            -Command "npm run dev -- --configLoader runner --host 0.0.0.0 --port $WebPort --strictPort" `
            -Environment @{ "VITE_API_BASE_URL" = "" } `
            -WorkingDirectory (Join-Path $repoRoot "apps/web") `
            -Port $WebPort
    }
}
catch {
    Stop-StartedProcesses -Processes $started
    throw
}

$payload = [pscustomobject]@{
    started_at = (Get-Date).ToString("s")
    repo_root = $repoRoot
    queue_mode = $queueMode
    agent_provider = $agentProvider
    processes = $started
}

$temporaryPidFile = "$pidFile.tmp"
$payload | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $temporaryPidFile -Encoding UTF8
Move-Item -LiteralPath $temporaryPidFile -Destination $pidFile -Force

Write-Host ""
Write-Host "Started local services:"
foreach ($entry in $started) {
    Write-Host ("- {0} (PID {1}) log: {2}" -f $entry.name, $entry.pid, $entry.log)
}
Write-Host ""
if (-not $SkipApi) { Write-Host "API:    http://localhost:$ApiPort" }
if (-not $SkipWeb) { Write-Host "Web:    http://localhost:$WebPort" }
if (-not $SkipBridge) { Write-Host "Bridge: http://localhost:$BridgePort/mcp" }
if (-not $startWorker) {
    Write-Host "Worker: not started (inline mode)"
}
Write-Host ""
Write-Host "Stop with: .\stop.cmd"

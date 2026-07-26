param(
    [switch]$SkipBridge,
    [switch]$SkipApi,
    [switch]$SkipWorker,
    [switch]$SkipWeb,
    [switch]$InlineMode,
    [switch]$ArqMode,
    [switch]$StubAgent,
    [switch]$HelloAgents,
    [int]$BridgePort = 8085,
    [int]$ApiPort = 8000,
    [int]$WebPort = 5173
)

$ErrorActionPreference = "Stop"

$repoRoot = Split-Path -Parent $PSScriptRoot
$runDir = Join-Path $repoRoot ".tmp\local-dev"
$logDir = Join-Path $runDir "logs"
$pidFile = Join-Path $runDir "pids.json"

New-Item -ItemType Directory -Force -Path $logDir | Out-Null

function ConvertTo-CmdLiteral {
    param([string]$Value)
    return '"' + ($Value -replace '"', '""') + '"'
}

function Start-ManagedProcess {
    param(
        [string]$Name,
        [string]$Command,
        [hashtable]$Environment = @{},
        [string]$WorkingDirectory = $repoRoot
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

    Start-Sleep -Milliseconds 300
    if ($process.HasExited) {
        throw "Process $Name exited immediately. Check log: $logPath"
    }

    return [pscustomobject]@{
        name = $Name
        pid = $process.Id
        log = $logPath
        command = $Command
    }
}

$queueMode = if ($ArqMode) { "arq" } else { "inline" }
$agentProvider = if ($HelloAgents) { "helloagents" } else { "stub" }

$sharedEnv = @{}
if ($InlineMode -or -not $ArqMode) {
    $sharedEnv["TRAVELMIND_QUEUE_MODE"] = "inline"
}
if ($ArqMode) {
    $sharedEnv["TRAVELMIND_QUEUE_MODE"] = "arq"
    $sharedEnv["TRAVELMIND_REDIS_URL"] = "redis://127.0.0.1:6379/0"
}
if ($StubAgent -or -not $HelloAgents) {
    $sharedEnv["TRAVELMIND_AGENT_PROVIDER"] = "stub"
}
if ($HelloAgents) {
    $sharedEnv["TRAVELMIND_AGENT_PROVIDER"] = "helloagents"
}

$started = @()
$startWorker = -not $SkipWorker -and $ArqMode

if (-not $SkipBridge) {
    $started += Start-ManagedProcess `
        -Name "groksearch-bridge" `
        -Command "uv run --project apps/groksearch-bridge uvicorn travelmind_groksearch_bridge.main:app --host 127.0.0.1 --port $BridgePort"
}

if (-not $SkipApi) {
    $started += Start-ManagedProcess `
        -Name "api" `
        -Command "uv run --project apps/api uvicorn travelmind_api.main:app --reload --host 127.0.0.1 --port $ApiPort" `
        -Environment $sharedEnv
}

if ($startWorker) {
    $started += Start-ManagedProcess `
        -Name "worker" `
        -Command "uv run --project apps/worker python -m travelmind_worker.worker" `
        -Environment $sharedEnv
}

if (-not $SkipWeb) {
    $started += Start-ManagedProcess `
        -Name "web" `
        -Command "npm run dev -- --configLoader runner --host 0.0.0.0 --port $WebPort" `
        -Environment @{ "VITE_API_BASE_URL" = "http://localhost:$ApiPort" } `
        -WorkingDirectory (Join-Path $repoRoot "apps/web")
}

$payload = [pscustomobject]@{
    started_at = (Get-Date).ToString("s")
    repo_root = $repoRoot
    queue_mode = $queueMode
    agent_provider = $agentProvider
    processes = $started
}

$payload | ConvertTo-Json -Depth 6 | Set-Content -Path $pidFile -Encoding UTF8

Write-Host ""
Write-Host "Started local services:"
foreach ($entry in $started) {
    Write-Host ("- {0} (PID {1}) log: {2}" -f $entry.name, $entry.pid, $entry.log)
}
Write-Host ""
Write-Host "API:    http://localhost:$ApiPort"
Write-Host "Web:    http://localhost:$WebPort"
Write-Host "Bridge: http://localhost:$BridgePort/mcp"
if (-not $startWorker) {
    Write-Host "Worker: not started (inline mode)"
}
Write-Host ""
Write-Host "Stop with: .\scripts\stop-local.ps1"

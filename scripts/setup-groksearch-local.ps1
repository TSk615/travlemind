param(
  [switch]$CheckOnly,
  [switch]$ForceReinstall,
  [switch]$PrintEnvTemplate
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot
$uvCacheDir = Join-Path $projectRoot ".uv-cache"

Write-Host "[setup] Syncing bridge environment..."
uv --cache-dir $uvCacheDir sync --project apps/groksearch-bridge

$uvArgs = @(
  "--cache-dir",
  $uvCacheDir,
  "run",
  "--project",
  "apps/groksearch-bridge",
  "python",
  "-m",
  "travelmind_groksearch_bridge.bootstrap"
)

if (-not $CheckOnly) {
  $uvArgs += "--install-upstream"
}

if ($ForceReinstall) {
  $uvArgs += "--force-reinstall"
}

if ($PrintEnvTemplate) {
  $uvArgs += "--print-env-template"
}

$uvArgs += "--check"

Write-Host "[setup] Running GrokSearch bootstrap..."
uv @uvArgs

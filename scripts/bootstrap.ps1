#Requires -Version 5.1
<#
.SYNOPSIS
  One-command bootstrap for claude-master on Windows (native, PowerShell).
  Installs Python deps, Go modules, npm deps, and builds hookshim.exe /
  watchdog.exe / gateway.exe. Idempotent. Never prints secrets.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
#>
[CmdletBinding()]
param(
  [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

# Augment PATH with well-known install locations (fresh shells often miss them).
foreach ($dir in @("C:\Program Files\Go\bin", "D:\nodejs", "$env:ProgramFiles\nodejs")) {
  if ((Test-Path $dir) -and ($env:Path -notlike "*$dir*")) { $env:Path += ";$dir" }
}

Write-Host "==> Python deps"
& $Python -m pip install -U pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "pip bootstrap failed" }
& $Python -m pip install -e "$Root[dev]" psutil
if ($LASTEXITCODE -ne 0) { throw "pip install deps failed" }

Write-Host "==> Go modules + binaries"
$go = Get-Command go -ErrorAction SilentlyContinue
if ($null -eq $go) {
  Write-Warning "go not found; install with: winget install GoLang.Go -e. Gateway/shim tests will skip."
} else {
  go version
  foreach ($mod in @("gateway", "hookshim", "watchdog")) {
    $dir = Join-Path $Root $mod
    if (Test-Path (Join-Path $dir "go.mod")) {
      Write-Host "$ go mod tidy ($mod)"
      & go mod tidy
      if ($LASTEXITCODE -ne 0) { Write-Warning "go mod tidy failed in $mod" }
    }
  }
  Write-Host "$ go build hookshim.exe / watchdog.exe / gateway.exe"
  Push-Location (Join-Path $Root "hookshim")
  & go build -o hookshim.exe .
  if ($LASTEXITCODE -ne 0) { throw "hookshim build failed" }
  Pop-Location
  Push-Location (Join-Path $Root "watchdog")
  & go build -o watchdog.exe .
  if ($LASTEXITCODE -ne 0) { throw "watchdog build failed" }
  Pop-Location
  Push-Location (Join-Path $Root "gateway")
  & go build -o gateway.exe ./cmd/gateway
  if ($LASTEXITCODE -ne 0) { throw "gateway build failed" }
  Pop-Location
}

Write-Host "==> TypeScript / studio"
$npm = Get-Command npm -ErrorAction SilentlyContinue
if ($null -eq $npm) {
  Write-Warning "npm not found; studio tests will skip."
} else {
  if (Test-Path (Join-Path $Root "package.json")) {
    Push-Location $Root
    & npm install --no-fund --no-audit
    Pop-Location
  }
  $studioPkg = Join-Path $Root "studio\package.json"
  if (Test-Path $studioPkg) {
    Push-Location (Join-Path $Root "studio")
    & npm install --no-fund --no-audit
    Pop-Location
  }
}

Write-Host "==> Bootstrap complete"
& $Python --version
if (Get-Command go -ErrorAction SilentlyContinue) { go version }
if (Get-Command node -ErrorAction SilentlyContinue) { node --version }
Write-Host "Run tests with: python -m pytest -q"
Write-Host "Start stack with: powershell -ExecutionPolicy Bypass -File scripts\start.ps1"

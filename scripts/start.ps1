#Requires -Version 5.1
<#
.SYNOPSIS
  One-command start for claude-master on Windows (native, PowerShell).
  Starts brain daemon, gateway, and watchdog as child processes with
  Windows process handling. Paths handle spaces and backslashes via
  quoted Join-Path everywhere. No WSL, no Unix sockets (TCP loopback).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1
  powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -DbPath "D:\my dir\brain.db"
#>
[CmdletBinding()]
param(
  [string]$DbPath = "",
  [string]$TcpAddr = "127.0.0.1:7772",
  [string]$HttpHost = "127.0.0.1",
  [int]$HttpPort = 7700,
  [string]$GatewayConfig = "",
  [switch]$NoWatchdog
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
foreach ($dir in @("C:\Program Files\Go\bin", "D:\nodejs", "$env:ProgramFiles\nodejs")) {
  if ((Test-Path $dir) -and ($env:Path -notlike "*$dir*")) { $env:Path += ";$dir" }
}
if ([string]::IsNullOrWhiteSpace($DbPath)) {
  $DbPath = Join-Path ([System.IO.Path]::GetTempPath()) "claude_brain.db"
}
if ([string]::IsNullOrWhiteSpace($GatewayConfig)) {
  $GatewayConfig = Join-Path $Root "gateway\config.json"
}
$LogDir = Join-Path ([System.IO.Path]::GetTempPath()) "claude-master-logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$procs = @()
function Start-Child($Exe, $ProcArgs, $Name) {
  $log = Join-Path $LogDir "$Name.log"
  Write-Host "starting $Name -> $log"
  Write-Host "  $Exe $($ProcArgs -join ' ')"
  $p = Start-Process -FilePath $Exe -ArgumentList $ProcArgs -WorkingDirectory $Root `
    -RedirectStandardOutput $log -RedirectStandardError "$log.err" `
    -NoNewWindow -PassThru
  $script:procs += [pscustomobject]@{ Name = $Name; Proc = $p; Log = $log }
}

try {
  # 1. Brain daemon (TCP hook IPC + HTTP).
  Start-Child "python" @("-m", "brain.server", "--db", $DbPath, "--tcp", $TcpAddr,
    "--host", $HttpHost, "--port", "$HttpPort") "brain"

  # Wait for /health (fail fast with log tail).
  $health = "http://${HttpHost}:${HttpPort}/health"
  $deadline = (Get-Date).AddSeconds(30)
  while ((Get-Date) -lt $deadline) {
    try {
      $r = Invoke-RestMethod -Uri $health -TimeoutSec 2
      if ($r.status -eq "ok") { break }
    } catch { Start-Sleep -Milliseconds 300 }
  }
  try {
    $r = Invoke-RestMethod -Uri $health -TimeoutSec 5
    Write-Host "brain healthy: $($r | ConvertTo-Json -Compress)"
  } catch {
    throw "brain daemon not healthy at $health; see $LogDir\brain.log"
  }

  # 2. Gateway.
  $gwExe = Join-Path $Root "gateway\gateway.exe"
  if (-not (Test-Path $gwExe)) { throw "missing $gwExe; run scripts\bootstrap.ps1 first" }
  $env:CLAUDE_BRAIN_TCP = $TcpAddr
  Start-Child $gwExe @("--config", $GatewayConfig) "gateway"

  # 3. Watchdog (Windows process handling via Go os/exec; env-configured).
  if (-not $NoWatchdog) {
    $wdExe = Join-Path $Root "watchdog\watchdog.exe"
    if (-not (Test-Path $wdExe)) { throw "missing $wdExe; run scripts\bootstrap.ps1 first" }
    $env:BRAIN_API_URL = "http://${HttpHost}:${HttpPort}"
    if (-not $env:BRAIN_DAEMON_CMD) {
      $env:BRAIN_DAEMON_CMD = "python -m brain.server --db `"$DbPath`" --tcp `"$TcpAddr`" --host $HttpHost --port $HttpPort"
    }
    Start-Child $wdExe @() "watchdog"
  }

  Write-Host ""
  Write-Host "claude-master is running (Ctrl+C to stop):"
  Write-Host "  brain    http://${HttpHost}:${HttpPort}/health   hooks tcp://$TcpAddr"
  Write-Host "  gateway  http://localhost:8080/health (ANTHROPIC_BASE_URL=http://localhost:8080)"
  Write-Host "  logs     $LogDir"
  Write-Host ""
  Write-Host 'Point Claude Code at the gateway:'
  Write-Host '  $env:ANTHROPIC_BASE_URL="http://localhost:8080"; $env:ANTHROPIC_API_KEY="dummy"; claude'

  while ($true) {
    Start-Sleep -Seconds 2
    foreach ($c in $procs) {
      if ($c.Proc.HasExited) { throw "$($c.Name) exited (code $($c.Proc.ExitCode)); see $($c.Log)" }
    }
  }
} finally {
  foreach ($c in $procs) {
    try {
      if (-not $c.Proc.HasExited) {
        Stop-Process -Id $c.Proc.Id -Force -ErrorAction SilentlyContinue
        Write-Host "stopped $($c.Name) (pid $($c.Proc.Id))"
      }
    } catch { }
  }
}

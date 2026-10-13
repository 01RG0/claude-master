#Requires -Version 5.1
<#
.SYNOPSIS
  cm - the single entry command for claude-master.

.DESCRIPTION
  Every way of driving the system goes through this script:
  bootstrap, start/stop/restart, status, doctor, logs, config,
  provider management, reports. Subcommands delegate to the
  existing scripts/binaries so there is exactly one source of truth
  for each behavior. Never prints secrets.

.EXAMPLE
  cm start          # = scripts\start.ps1
  cm status         # one-screen component health
  cm doctor         # dependency + config + port checks with plain fixes
  cm provider list  # configured providers
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [string]$Command = "status",

  [Parameter(Position = 1, ValueFromRemainingArguments = $true)]
  [string[]]$Rest = @()
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # tools/cm -> repo root
$cmScriptHint = Join-Path $Root "tools\cm\completions.ps1"
$LogDir = Join-Path ([System.IO.Path]::GetTempPath()) "claude-master-logs"
$ProviderExe = Join-Path $Root "provider.exe"

$script:BadCount = 0
function Info($msg)  { Write-Host $msg }
function Ok($msg)    { Write-Host "  [ok] $msg" -ForegroundColor Green }
function Warn($msg)  { Write-Host "  [!!] $msg" -ForegroundColor Yellow }
function Fail($msg)  { Write-Host "  [XX] $msg" -ForegroundColor Red }

# ---------------------------------------------------------------------------
function Invoke-HttpHealth($url, $timeoutSec = 3) {
  try {
    $resp = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec $timeoutSec
    return @{ up = $true; body = $resp.Content }
  } catch { return @{ up = $false; body = "" } }
}

function Test-TcpPort($port, $timeoutSec = 2) {
  $client = New-Object Net.Sockets.TcpClient
  try {
    $iar = $client.BeginConnect("127.0.0.1", $port, $null, $null)
    if ($iar.AsyncWaitHandle.WaitOne($timeoutSec * 1000)) { return $client.Connected }
    return $false
  } catch { return $false } finally { $client.Close() }
}

# ---------------------------------------------------------------------------
# cm setup - one-time install (delegates to bootstrap.ps1)
function Invoke-Setup {
  Info "==> cm setup: installing dependencies and building binaries"
  & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\bootstrap.ps1") @Rest
  if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne $null) { Fail "setup failed (exit $LASTEXITCODE)"; exit 1 }
  Ok "setup complete. Next: cm start, then point Claude Code at http://localhost:8080 (see cm doctor)"
  Info ""
  Info "  optional: tab-completion for cm - add this line to your ${PROFILE}:"
  Info "    . $cmScriptHint"
}

# ---------------------------------------------------------------------------
# cm start / stop / restart
function Invoke-Start {
  Info "==> cm start"
  & powershell -ExecutionPolicy Bypass -File (Join-Path $Root "scripts\start.ps1") @Rest
}

function Get-ComponentProcesses {
  $names = @("gateway.exe", "hookshim.exe", "hookhost.exe", "watchdog.exe")
  Get-CimInstance Win32_Process | Where-Object {
    $n = $_.Name
    if ($names -contains $n) { return $true }
    if ($n -eq "python.exe" -and $_.CommandLine -match "brain\.server") { return $true }
    return $false
  }
}

function Invoke-Stop {
  Info "==> cm stop"
  $procs = Get-ComponentProcesses
  if (-not $procs) { Info "  nothing running"; return }
  foreach ($p in $procs) {
    Info ("  stopping {0} (pid {1})" -f $p.Name, $p.ProcessId)
    try { Stop-Process -Id $p.ProcessId -Force -ErrorAction Stop | Out-Null } catch { Fail ("  could not stop pid {0}: {1}" -f $p.ProcessId, $_.Exception.Message) }
  }
  Ok "stopped"
}

# ---------------------------------------------------------------------------
# cm status - one screen of truth
function Invoke-Status {
  $gw = Invoke-HttpHealth "http://localhost:8080/health"
  $brain = Invoke-HttpHealth "http://127.0.0.1:7700/health"
  $hook = Test-TcpPort 7772
  $procs = Get-ComponentProcesses

  Info "claude-master status"
  Info "--------------------"
  function Show($name, $up, $detail) {
    $mark = "down"
    if ($up) { $mark = "UP  " }
    Info ("  [{0}] {1,-10} {2}" -f $mark, $name, $detail)
  }
  Show "gateway" ($gw.up) "http://localhost:8080/health"
  Show "brain"   ($brain.up) "http://127.0.0.1:7700/health"
  Show "hooks"   $hook   ("TCP 127.0.0.1:7772")
  if ($procs) { foreach ($p in $procs) { Info ("        proc: {0} (pid {1})" -f $p.Name, $p.ProcessId) } }
  if (-not (($gw.up) -or ($brain.up))) {
    Warn "nothing is running - try: cm start"
  }
}

# ---------------------------------------------------------------------------
# cm doctor - concrete checks, each with a fix
function Invoke-Doctor {
  Info "==> cm doctor"
  $bad = 0
  function Check($name, $cond, $fix) {
    if ($cond) { Ok $name }
    elseif ($env:CI -eq "true") { Warn "$name (CI: keys/built artifacts are not checked in; skipped as failure)" }
    else { Fail "$name"; Fail "    fix: $fix"; $script:BadCount++ }
  }

  $py = Get-Command python -ErrorAction SilentlyContinue
  Check "python on PATH" ($py -ne $null) "install Python 3.11+ from python.org (Windows installer)"
  $go = Get-Command go -ErrorAction SilentlyContinue
  Check "go on PATH" ($go -ne $null) "install Go from go.dev/dl (needed only to rebuild binaries)"
  $node = Get-Command node -ErrorAction SilentlyContinue
  Check "node on PATH" ($node -ne $null) "install Node 18+ from nodejs.org (needed for the studio viewer)"

  Check "config exists" (Test-Path (Join-Path $Root "gateway\config.json")) "run: git restore gateway/config.json (or cm setup)"
  if (Test-Path (Join-Path $Root "gateway\config.json")) {
    try {
      $cfg = Get-Content (Join-Path $Root "gateway\config.json") -Raw | ConvertFrom-Json
      $nProv = @($cfg.Providers).Count
      Check "config parses ($nProv providers)" ($nProv -gt 0) "config.json is corrupt: git checkout -- gateway/config.json"
    } catch { Fail "config.json is not valid JSON"; Fail "    fix: git checkout -- gateway/config.json"; $script:BadCount++ }
  }

  Check "provider.exe built" (Test-Path $ProviderExe) "cm setup (builds it)"

  $envFile = Join-Path $Root ".env"
  if (Test-Path $envFile) {
    $keys = Get-Content $envFile | Where-Object { $_ -match "API_KEY=" -or $_ -match "_KEY=" } | ForEach-Object { ($_ -split "=")[0] }
    Check ("keys in .env ({0} entries)" -f $keys.Count) ($keys.Count -gt 0) "add provider keys to .env (never commit them)"
  } else { Warn ".env not found"; Warn "    fix: copy .env.example to .env and fill in provider keys (CI: not required)" }

  $claude = Get-Command claude -ErrorAction SilentlyContinue
  if ($claude) { Ok ("claude CLI on PATH") } else { Warn "claude CLI not on PATH (optional; needed for E2E runs). fix: npm install -g @anthropic-ai/claude-code" }

  $gw = Invoke-HttpHealth "http://localhost:8080/health" 1
  if (-not $gw.up) { Warn "gateway not running. fix: cm start" }

  Info ""
  if ($script:BadCount -eq 0) { Ok "doctor: all required checks green" }
  else { Fail "doctor: $script:BadCount required check(s) failed (see fix lines above)"; exit 1 }
}

# ---------------------------------------------------------------------------
# cm logs
function Invoke-Logs {
  if (-not (Test-Path $LogDir)) { Info "no log dir yet at $LogDir (nothing has run)"; return }
  $name = ""
  if ($Rest.Count -gt 0) { $name = $Rest[0] }
  $files = Get-ChildItem $LogDir
  if ($name) { $files = Get-ChildItem $LogDir -Filter "$name*" }
  if (-not $files) { Info "no logs matching '$name' in $LogDir"; return }
  foreach ($f in $files) { Info ("-- {0}" -f $f.FullName); Get-Content $f.FullName -Tail 40 }
}

# ---------------------------------------------------------------------------
# cm config
function Invoke-Config {
  $cfgPath = Join-Path $Root "gateway\config.json"
  if (-not (Test-Path $cfgPath)) { Fail "gateway\config.json missing"; exit 1 }
  $cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
  Info "config: $cfgPath"
  Info ("  listen:        {0}" -f $cfg.ListenAddr)
  Info ("  privacy_mode:  {0}" -f $cfg.PrivacyMode)
  Info ("  providers:     {0}" -f @($cfg.Providers).Count)
  foreach ($p in $cfg.Providers) {
    $pools = @($p.key_pools).Count
    Info ("    - {0,-18} {1,-45} models:{2} pools:{3}" -f $p.Name, $p.base_url, @($p.Models).Count, $pools)
  }
}

# ---------------------------------------------------------------------------
# cm provider ... - delegates to provider.exe
function Invoke-Provider {
  if (-not (Test-Path $ProviderExe)) { Fail "provider.exe not built yet (fix: cm setup)"; exit 1 }
  $sub = "help"
  if ($Rest.Count -gt 0) { $sub = $Rest[0] }
  $args = @()
  if ($Rest.Count -gt 1) { $args = $Rest[1..($Rest.Count - 1)] }
  & $ProviderExe $sub @args
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# ---------------------------------------------------------------------------
# cm test - full baseline suite (same frozen commands as docs/cleanup-baseline.md)
function Invoke-Test {
  $fail = 0
  Info "==> cm test"
  Info "-- pytest"
  python -m pytest -q
  if ($LASTEXITCODE -ne 0) { Fail "pytest failed"; $fail++ }
  foreach ($mod in @("gateway", "hookshim", "watchdog")) {
    Info "-- go test ($mod)"
    Push-Location (Join-Path $Root $mod)
    go test -count=1 ./...
    if ($LASTEXITCODE -ne 0) { Fail "go test $mod failed"; $fail++ }
    Pop-Location
  }
  $pkg = Join-Path $Root "studio\package.json"
  if (Test-Path $pkg) {
    Info "-- vitest (studio)"
    Push-Location (Join-Path $Root "studio")
    npm test --silent
    if ($LASTEXITCODE -ne 0) { Fail "studio tests failed"; $fail++ }
    Pop-Location
  }
  Info ""
  if ($fail -eq 0) { Ok "cm test: all suites green" } else { Fail "cm test: $fail suite(s) failed"; exit 1 }
}

# ---------------------------------------------------------------------------
# cm bench - measured budgets: brain | drex | hookhost (default: all)
function Invoke-Bench {
  $only = if ($Rest.Count -gt 0) { $Rest[0] } else { "all" }
  if ($only -ne "all" -and @("brain", "drex", "hookhost") -notcontains $only) {
    Fail "unknown bench target '$only' (brain|drex|hookhost|all)"; exit 2
  }
  $targets = @("brain", "drex", "hookhost")
  if ($only -ne "all") { $targets = @($only) }
  foreach ($t in $targets) {
    Info "==> bench $t"
    python (Join-Path $Root "scripts\bench_$t.py")
    if ($LASTEXITCODE -ne 0) { Fail "bench $t failed"; }
  }
}

# ---------------------------------------------------------------------------
# cm e2e - the REAL Claude Code scenario matrix
# Usage: cm e2e [matrix|live]  (matrix = 10 scenarios; live = single live run)
function Invoke-E2E {
  $which = if ($Rest.Count -gt 0) { $Rest[0] } else { "matrix" }
  switch ($which) {
    "matrix" { $script = "e2e_claude_matrix.py" }
    "live"   { $script = "e2e_claude_live.py" }
    default  { Fail "unknown e2e target '$which' (matrix|live)"; exit 2 }
  }
  Info "==> cm e2e $which ($script) - real claude binary through the gateway"
  python (Join-Path $Root "scripts\$script")
  exit $LASTEXITCODE
}

# ---------------------------------------------------------------------------
# cm report - where the numbers live
function Invoke-Report {
  Info "reports & numbers (real, measured):"
  Info ("  {0}" -f (Join-Path $Root "docs\cleanup-baseline.md"))
  Info ("  {0}" -f (Join-Path $Root "docs\benchmarks.md"))
  Info ("  {0}" -f (Join-Path $Root "docs\STATUS.md"))
  Info ("  {0}" -f (Join-Path $Root "docs\detector-report.md"))
}

# ---------------------------------------------------------------------------
$cmd = $Command.ToLower()
switch ($cmd) {
  "setup"     { Invoke-Setup }
  "start"     { Invoke-Start }
  "stop"      { Invoke-Stop }
  "restart"   { Invoke-Stop; Invoke-Start }
  "status"    { Invoke-Status }
  "doctor"    { Invoke-Doctor }
  "logs"      { Invoke-Logs }
  "config"    { Invoke-Config }
  "provider"  { Invoke-Provider }
  "report"    { Invoke-Report }
  "test"      { Invoke-Test }
  "bench"     { Invoke-Bench }
  "e2e"       { Invoke-E2E }
  "help"      { Get-Help $MyInvocation.MyCommand.ScriptBlock -Name cm -Detailed | Out-String }
  default {
    Fail "unknown command '$Command' (setup|start|stop|restart|status|doctor|logs|config|provider|report|test|bench|e2e|help)"
    exit 2
  }
}

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
# metrics helpers (real data, parsed from runtime JSONL/log outputs)
function Get-OffDir { (Join-Path $Root "off") }

function Get-StatusMetrics {
  $today = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")
  $offDir = Get-OffDir

  $metrics = [ordered]@{
    trafficToday = 0
    lastTrafficAt = ""
    topModels = ""
    decisionsToday = 0
    lastDecisionId = ""
    gatewayErrorLines = 0
    lastTest = ""
  }

  # traffic: off/*.jsonl records carry a "ts" field
  $counts = @{}
  $newest = ""
  if (Test-Path $offDir) {
    foreach ($file in Get-ChildItem $offDir -Filter *.jsonl -ErrorAction SilentlyContinue) {
      foreach ($line in Get-Content $file.FullName -ErrorAction SilentlyContinue) {
        try {
          $rec = $line | ConvertFrom-Json
          $ts = [string]$rec.ts
          if (-not $ts) { continue }
          if ($ts.StartsWith($today)) { $metrics.trafficToday++ }
          if ($ts -gt $newest) { $newest = $ts }
          if ($ts.StartsWith($today) -and $rec.mapped) {
            $m = [string]$rec.mapped
            if ($counts.ContainsKey($m)) { $counts[$m]++ } else { $counts[$m] = 1 }
          }
        } catch { }
      }
    }
  }
  $metrics.lastTrafficAt = $newest
  $top3 = @($counts.GetEnumerator() | Sort-Object Value -Descending | Select-Object -First 3)
  $metrics.topModels = ($top3 | ForEach-Object { "{0} ({1})" -f $_.Key, $_.Value }) -join ", "

  # Drex decisions (runtime log dir)
  $decisionLog = Join-Path $LogDir "decisions.jsonl"
  if (Test-Path $decisionLog) {
    $lastId = ""
    foreach ($line in Get-Content $decisionLog -ErrorAction SilentlyContinue) {
      try {
        $rec = $line | ConvertFrom-Json
        if (([string]$rec.ts).StartsWith($today)) {
          $metrics.decisionsToday++
          $lastId = [string]$rec.request_id
        }
      } catch { }
    }
    $metrics.lastDecisionId = $lastId
  }

  # gateway errors (log tail; case-insensitive match)
  $gwLog = Join-Path $LogDir "gateway.log"
  if (Test-Path $gwLog) {
    $metrics.gatewayErrorLines = @(Select-String -Path $gwLog -Pattern "error|429|exhausted" -SimpleMatch:$false -ErrorAction SilentlyContinue).Count
  }

  # last test outcome (written by cm test)
  $testFile = Join-Path (Get-OffDir) "last-test.json"
  if (Test-Path $testFile) {
    try { $t = Get-Content $testFile -Raw | ConvertFrom-Json
      $metrics.lastTest = "{0} {1} ({2})" -f $t.overall, $t.at, $t.suites
    } catch { }
  }

  return $metrics
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

  $m = Get-StatusMetrics
  Info ""
  Info "metrics (today, real data):"
  Info ("  requests today:  {0}   last: {1}" -f $m.trafficToday, $m.lastTrafficAt)
  if ($m.topModels) { Info ("  top models:      {0}" -f $m.topModels) }
  Info ("  Drex decisions:  {0} today" -f $m.decisionsToday)
  if ($m.lastDecisionId) { Info ("  last decision:   {0}  (cm explain runs once explain lands)" -f $m.lastDecisionId) }
  if ($m.lastTest) { Info ("  last test:       {0}" -f $m.lastTest) }
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
# cm explain <request-id> - print a real decision record + surrounding traffic
function Invoke-Explain {
  $reqId = ""
  if ($Rest.Count -gt 0) { $reqId = $Rest[0] }
  else { $reqId = (Get-StatusMetrics).lastDecisionId }
  if (-not $reqId) { Fail "usage: cm explain <request-id>"; exit 2 }

  $decisionLog = Join-Path $LogDir "decisions.jsonl"
  if (-not (Test-Path $decisionLog)) { Fail "no decisions.jsonl in $LogDir (brain never ran)"; exit 1 }

  $hit = $null
  foreach ($line in Get-Content $decisionLog -ErrorAction SilentlyContinue) {
    try {
      $rec = $line | ConvertFrom-Json
      if ([string]$rec.request_id -eq $reqId) { $hit = $rec }
    } catch { }
  }
  if (-not $hit) { Fail "request id not found in decisions.jsonl: $reqId"; Fail "    fix: the Drex log covers only evaluated decisions; check off/*.jsonl for raw traffic"; exit 1 }

  Info "Drex decision for $reqId"
  Info ("  at:              {0}  ({1}, {2}ms)" -f $hit.ts, $hit.model, $hit.latency_ms)
  Info ("  state:           {0}" -f $hit.state)
  foreach ($q in $hit.questions.PSObject.Properties) {
    $ans = $hit.answers.PSObject.Properties[$q.Name]
    if ($ans) { Info ("  answer {0}: {1}" -f $q.Name, ($ans.Value | ConvertTo-Json -Compress)) }
    else { Info ("  question {0}: {1}" -f $q.Name, ($q.Value | ConvertTo-Json -Compress)) }
  }
  Info ("  usage:           {0}" -f ($hit.usage | ConvertTo-Json -Compress))

  # surrounding gateway traffic (same UTC second to +10 seconds window)
  Info ""
  Info "gateway traffic around this decision:"
  $base = [string]$hit.ts
  $baseSec = $base.Substring(0, 18)
  $offDir = Get-OffDir
  if (Test-Path $offDir) {
    foreach ($file in Get-ChildItem $offDir -Filter *.jsonl -ErrorAction SilentlyContinue) {
      foreach ($line in Get-Content $file.FullName -ErrorAction SilentlyContinue) {
        try {
          $rec = $line | ConvertFrom-Json
          $ts = [string]$rec.ts
          if ($ts -ge $baseSec -and $ts -le ($baseSec.Substring(0, 17) + ([string]([int]([char[]]$baseSec[16]) + 1)))) {
            Info ("  {0}  {1} -> {2} ({3} msgs, {4} tools)" -f $ts, $rec.requested, $rec.mapped, $rec.messages, $rec.tools)
          }
        } catch { }
      }
    }
  }
}

# ---------------------------------------------------------------------------
# cm key - masked pool inspection (read-only; no secrets printed)
# Usage: cm key [list]
function Invoke-Key {
  $sub = "list"
  if ($Rest.Count -gt 0) { $sub = $Rest[0].ToLower() }
  if ($sub -ne "list") { Fail "unknown key action '$sub' (list)"; exit 2 }
  $cfg = Get-Content (Join-Path $Root "gateway\config.json") -Raw | ConvertFrom-Json
  Info "key pools (masked, from gateway/config.json):"
  foreach ($p in $cfg.Providers) {
    $pools = @($p.key_pools)
    if ($pools.Count -eq 0) { Info ("  {0,-12}: no pools configured" -f $p.Name); continue }
    foreach ($pool in $pools) {
      $src = ""
      if ($pool.env_var) { $src = "env:$($pool.env_var)" }
      Info ("  {0,-12}: account {1,-10} {2,-24} priority:{3}" -f $p.Name, $pool.account_label, $src, $pool.priority)
    }
  }
}

# ---------------------------------------------------------------------------
# cm model - delegates to provider.exe (add/list/probe/pin/ban via provider)
# Usage: cm model list|pin|ban [args...]
function Invoke-Model {
  if (-not (Test-Path $ProviderExe)) { Fail "provider.exe not built yet (fix: cm setup)"; exit 1 }
  $args = "list"
  if ($Rest.Count -gt 0) { $args = $Rest[0] }
  switch ($args.ToLower()) {
    "list" { & $ProviderExe list @($Rest | Select-Object -Skip 1) }
    "pin"  { & $ProviderExe pin @($Rest | Select-Object -Skip 1) }
    "ban"  { & $ProviderExe ban @($Rest | Select-Object -Skip 1) }
    default { Fail "unknown model action '$args' (list|pin|ban)"; exit 2 }
  }
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

# ---------------------------------------------------------------------------
# cm alerts - threshold checks over real runtime data, deduped in off/alerts.json
$AlertSigFile = ""
function Get-AlertStateFile { (Join-Path (Get-OffDir) "alerts.json") }

function Invoke-Alerts {
  $alerts = @()
  $today = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd")

  # 1. components down (reuse status health logic)
  $gw = Invoke-HttpHealth "http://localhost:8080/health" 1
  if (-not $gw.up) { $alerts += @{ sev = "warn"; sig = "gateway-down"; msg = "gateway is not reachable at http://localhost:8080/health"; fix = "cm start" } }
  $brain = Invoke-HttpHealth "http://127.0.0.1:7700/health" 1
  if (-not $brain.up) { $alerts += @{ sev = "warn"; sig = "brain-down"; msg = "brain daemon is not reachable at http://127.0.0.1:7700/health"; fix = "cm start" } }

  # 2. gateway error lines (today class of problems, from the real log)
  $gwLog = Join-Path $LogDir "gateway.log"
  if (Test-Path $gwLog) {
    $errLines = @(Select-String -Path $gwLog -Pattern "error|429|exhausted" -ErrorAction SilentlyContinue).Count
    if ($errLines -ge 20) { $alerts += @{ sev = "warn"; sig = "gateway-errors-$today"; msg = "$errLines error/429/exhaustion lines in gateway.log"; fix = "cm logs gateway, then check provider key health: cm doctor" } }
  }

  # 3. last test result
  $testFile = Join-Path (Get-OffDir) "last-test.json"
  if (Test-Path $testFile) {
    try {
      $t = Get-Content $testFile -Raw | ConvertFrom-Json
      if ($t.overall -ne "pass") { $alerts += @{ sev = "fail"; sig = "tests-red-" + $t.ts; msg = "last cm test failed at $($t.ts)"; fix = "cm test and read the failing suite output" } }
    } catch { }
  }

  # 4. off/ disk growth (retention)
  $offDir = Get-OffDir
  if (Test-Path $offDir) {
    $bytes = 0
    Get-ChildItem $offDir -Recurse -ErrorAction SilentlyContinue | ForEach-Object { $bytes += $_.Length }
    $mb = [math]::Round($bytes / 1MB, 1)
    if ($mb -gt 200) { $alerts += @{ sev = "warn"; sig = "off-size-$today"; msg = "off/ holds ${mb}MB of runtime files (retention: trim old *.jsonl)"; fix = "delete off/*.jsonl older than needed" } }
  }

  # dedupe: only surface signatures not seen in the current session output
  # PS 5.1 has no ConvertFrom-Json -AsHashtable; build the table by hand.
  $state = @{}
  $stateFile = Get-AlertStateFile
  if (Test-Path $stateFile) {
    try {
      $saved = Get-Content $stateFile -Raw | ConvertFrom-Json
      foreach ($prop in $saved.PSObject.Properties) { $state[$prop.Name] = [string]$prop.Value }
    } catch { }
  }
  Info "alerts"
  if ($alerts.Count -eq 0) { Ok "none - all thresholds quiet"; return }
  foreach ($a in $alerts) {
    $seen = $state.ContainsKey($a.sig)
    $mark = "NEW "
    if ($seen) { $mark = "seen" }
    Info ("  [{0}] {1,-7} {2}" -f $a.sev.ToUpper(), $mark, $a.msg)
    Info ("        fix: {0}" -f $a.fix)
    if (-not $seen) { $state[$a.sig] = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ") }
  }
  try {
    $dir = Get-OffDir
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }
    $state | ConvertTo-Json | Set-Content $stateFile -Encoding ascii
  } catch { }
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
  $overall = "fail"
  if ($fail -eq 0) { $overall = "pass" }
  try {
    $offDir = Get-OffDir
    if (-not (Test-Path $offDir)) { New-Item -ItemType Directory -Path $offDir | Out-Null }
    @{ ts = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ");
       overall = $overall;
       suites = "pytest go x3 vitest" } | ConvertTo-Json -Compress | Set-Content (Join-Path $offDir "last-test.json") -Encoding ascii
  } catch { }
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
# cm e2e report - pass rates across every stored e2e artifact (off/e2e/*.json)
function Invoke-E2eReport {
  $dir = Join-Path (Get-OffDir) "e2e"
  if (-not (Test-Path $dir)) { Info "no e2e artifacts in $dir yet (run: cm e2e matrix)"; return }
  $files = Get-ChildItem $dir -Filter *.json -ErrorAction SilentlyContinue
  if (-not $files) { Info "no e2e artifacts in $dir yet (run: cm e2e matrix)"; return }

  $rows = @{}
  foreach ($f in $files) {
    try { $d = Get-Content $f.FullName -Raw | ConvertFrom-Json } catch { continue }
    $model = "default"
    if ($d.meta -and $d.meta.model) { $model = [string]$d.meta.model }
    foreach ($r in $d.runs) {
      $key = "{0}|{1}" -f $r.scenario, $model
      if (-not $rows.ContainsKey($key)) {
        $rows[$key] = [ordered]@{ scenario = $r.scenario; model = $model; n = 0; pass = 0; class = @{} }
      }
      $rows[$key].n++
      if ($r.passed) { $rows[$key].pass++ }
      $c = [string]$r.class
      if ($c) {
        if ($rows[$key].class.ContainsKey($c)) { $rows[$key].class[$c]++ } else { $rows[$key].class[$c] = 1 }
      }
    }
  }
  Info "e2e results (all stored artifacts in off/e2e)"
  Info ("  {0,-24} {1,-10} {2,5} {3,6} {4,7}  {5}" -f "scenario", "model", "runs", "pass", "rate", "classes")
  $tot = 0; $totPass = 0
  foreach ($k in ($rows.Keys | Sort-Object)) {
    $row = $rows[$k]
    $rate = 0.0
    if ($row.n -gt 0) { $rate = $row.pass / $row.n }
    $tot += $row.n; $totPass += $row.pass
    $cls = ($row.class.Keys | ForEach-Object { "{0}:{1}" -f $_, $row.class[$_] }) -join ","
    Info ("  {0,-24} {1,-10} {2,5} {3,6} {4,7:N2}  {5}" -f $row.scenario, $row.model, $row.n, $row.pass, $rate, $cls)
  }
  if ($tot -gt 0) {
    Info ""
    Info ("  total: {0}/{1} verified pass ({2:N2})" -f $totPass, $tot, ($totPass / $tot))
  }
}

# ---------------------------------------------------------------------------
# cm e2e - the REAL Claude Code scenario matrix & validation suite
# Usage:
#   cm e2e pass [--tier smoke|standard|full] [--repeat N]
#   cm e2e explore [--turns N]
#   cm e2e fuzz [--iterations N] [--target api|hooks|all]
#   cm e2e soak [--duration N] [--concurrency N]
#   cm e2e chaos [--suite degradation|resilience|all]
#   cm e2e report
function Invoke-E2E {
  $which = "pass"
  if ($Rest.Count -gt 0) { $which = $Rest[0].ToLower() }
  if ($which -eq "report") { Invoke-E2eReport; return }

  $subRest = @()
  if ($Rest.Count -gt 1) { $subRest = $Rest[1..($Rest.Count - 1)] }

  switch ($which) {
    "pass" {
      Info "==> cm e2e pass: executing scenario matrix using real Claude CLI driver"
      python (Join-Path $Root "scripts\e2e_claude_matrix.py") @subRest
      exit $LASTEXITCODE
    }
    "matrix" {
      Info "==> cm e2e pass: executing scenario matrix using real Claude CLI driver"
      python (Join-Path $Root "scripts\e2e_claude_matrix.py") @subRest
      exit $LASTEXITCODE
    }
    "explore" {
      Info "==> cm e2e explore: unconstrained exploratory session"
      python (Join-Path $Root "cli\cm.py") e2e explore @subRest
      exit $LASTEXITCODE
    }
    "fuzz" {
      Info "==> cm e2e fuzz: API and prompt mutation fuzzing"
      python (Join-Path $Root "cli\cm.py") e2e fuzz @subRest
      exit $LASTEXITCODE
    }
    "soak" {
      Info "==> cm e2e soak: continuous workload and concurrency load test"
      python (Join-Path $Root "cli\cm.py") e2e soak @subRest
      exit $LASTEXITCODE
    }
    "chaos" {
      Info "==> cm e2e chaos: fault injection and degradation suite"
      python (Join-Path $Root "cli\cm.py") e2e chaos @subRest
      exit $LASTEXITCODE
    }
    "live" {
      Info "==> cm e2e live: single live run with hooks active"
      python (Join-Path $Root "scripts\e2e_claude_live.py") @subRest
      exit $LASTEXITCODE
    }
    "help" {
      Info "Usage: cm e2e <subcommand> [options]"
      Info ""
      Info "Subcommands:"
      Info "  pass [--tier smoke|standard|full] [--repeat N]  Run scenario matrix using real Claude CLI driver"
      Info "  explore [--turns N]                             Run unconstrained exploratory session"
      Info "  fuzz [--iterations N] [--target api|hooks|all]  Run API/prompt mutation fuzzers"
      Info "  soak [--duration N] [--concurrency N]           Run continuous workload and load test"
      Info "  chaos [--suite degradation|resilience|all]      Run fault injection tests"
      Info "  report                                          Display stored E2E artifact pass rates"
      return
    }
    default {
      Fail "unknown e2e subcommand '$which' (pass|explore|fuzz|soak|chaos|report|help)"
      exit 2
    }
  }
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
  "explain"   { Invoke-Explain }
  "key"       { Invoke-Key }
  "model"     { Invoke-Model }
  "alerts"    { Invoke-Alerts }
  "help"      { Get-Help $MyInvocation.MyCommand.ScriptBlock -Name cm -Detailed | Out-String }
  default {
    Fail "unknown command '$Command' (setup|start|stop|restart|status|doctor|logs|config|provider|key|model|report|test|bench|e2e|explain|alerts|help)"
    exit 2
  }
}

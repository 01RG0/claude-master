# cm tab-completion for PowerShell.
#
# Install once: add this line to your $PROFILE (cm setup prints it, or run
# `cm completions | Add-Content $PROFILE` after creating the profile):
#
#   . D:\pRoG\claude-master\tools\cm\completions.ps1
#
# Works in PowerShell 5.1+; degrade gracefully if the profile lives elsewhere.
if (-not $IsWindows -and $PSVersionTable.PSVersion.Major -lt 5) { return }

$cmRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$cmScript = Join-Path $cmRoot "cm.ps1"
if (-not (Test-Path $cmScript)) { return }

$CmSubcommands = @(
  "setup", "start", "stop", "restart", "status", "doctor", "logs",
  "config", "provider", "report", "test", "bench", "e2e", "help"
)
$CmBenchTargets = @("brain", "drex", "hookhost", "all")
$CmE2eTargets = @("matrix", "live")
$CmLogNames = @("brain", "gateway", "watchdog")

Register-ArgumentCompleter -CommandName cm -Native -ScriptBlock {
  param($wordToComplete, $commandAst, $cursorPosition)
  $head = @($commandAst | Select-Object -First 3)
  $first = ""
  if ($head.Count -ge 3) { $first = $head[2].ToString() }   # cm <first> <rest>
  elseif ($head.Count -ge 2) { $first = $head[1].ToString() }

  $list = @()
  if ($first -eq "bench") { $list = $CmBenchTargets }
  elseif ($first -eq "e2e") { $list = $CmE2eTargets }
  elseif ($first -eq "logs") { $list = $CmLogNames }
  else { $list = $CmSubcommands }

  $list | Where-Object { $_ -like "$wordToComplete*" } | ForEach-Object { $_ }
} | Out-Null

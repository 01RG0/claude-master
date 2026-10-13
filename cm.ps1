#Requires -Version 5.1
<#
.SYNOPSIS
  cm.ps1 — claude-master CLI PowerShell wrapper.
#>
[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$ArgsList
)

$Root = $PSScriptRoot
$PyExe = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $PyExe)) {
    $PyExe = "python"
}

$CliPy = Join-Path $Root "cli\cm.py"
& $PyExe $CliPy @ArgsList
exit $LASTEXITCODE

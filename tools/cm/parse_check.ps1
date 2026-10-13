# Parse-check every PowerShell script under PS 5.1.
# Used by .github/workflows/ci.yml windows job; also runnable locally:
#   powershell -NoProfile -ExecutionPolicy Bypass -File tools/cm/parse_check.ps1
$bad = 0
$files = Get-ChildItem -Recurse -Include *.ps1,*.psm1 -Path tools,scripts,.github -ErrorAction SilentlyContinue
foreach ($f in $files) {
  $tokens = $null
  $errors = $null
  [System.Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$tokens, [ref]$errors) > $null
  if ($errors -and $errors.Count -gt 0) {
    Write-Host "PARSE FAIL: $($f.FullName)"
    foreach ($e in $errors) {
      Write-Host "  $($e.Message) (line $($e.Extent.StartLineNumber))"
    }
    $bad++
  }
}
if ($bad -gt 0) { exit 1 }
Write-Host "All clean, files checked: $($files.Count)"

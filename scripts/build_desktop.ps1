#Requires -Version 5.1
<#
.SYNOPSIS
  Builds, packages, and configures the native Windows desktop shell for claude-master.
.DESCRIPTION
  - Validates Windows WebView2 Evergreen runtime.
  - Generates desktop application icons (.ico / .png).
  - Installs/validates desktop dependencies (pywebview, pystray, pillow, pywin32).
  - Creates the portable Windows launcher (cm-desktop.cmd and cm-desktop.vbs).
  - Generates Windows Desktop and Start Menu shortcuts.
  - Optionally configures login autostart.
#>
[CmdletBinding()]
param(
  [switch]$InstallAutostart,
  [switch]$SkipShortcut
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Write-Host "=== Claude Master Desktop Shell Builder ===" -ForegroundColor Cyan
Write-Host "Repository root: $Root"

# 1. Verify Python
$pyExe = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $pyExe) {
  throw "Python 3 is required but not found in PATH."
}
Write-Host "[OK] Python detected: $pyExe" -ForegroundColor Green

# 2. Verify WebView2 Evergreen Runtime
$wv2Paths = @(
  "C:\Windows\System32\Microsoft-Edge-WebView\msedgewebview2.exe",
  "C:\Program Files (x86)\Microsoft\EdgeWebView\Application\155.0.4283.45\msedgewebview2.exe"
)
$wv2Found = $false
foreach ($p in $wv2Paths) {
  if (Test-Path $p) {
    Write-Host "[OK] WebView2 Runtime detected: $p" -ForegroundColor Green
    $wv2Found = $true
    break
  }
}
if (-not $wv2Found) {
  Write-Warning "WebView2 Evergreen Runtime was not detected in standard system locations. pywebview will attempt system fallback."
}

# 3. Ensure desktop Python dependencies
Write-Host "Verifying Python desktop dependencies..." -ForegroundColor Yellow
& python -m pip install -q pywebview pystray pillow psutil pywin32
if ($LASTEXITCODE -ne 0) {
  throw "Failed to install desktop dependencies."
}
Write-Host "[OK] Desktop dependencies verified." -ForegroundColor Green

# 4. Generate desktop icon files
Write-Host "Generating application icons..." -ForegroundColor Yellow
& python -c "
from desktop.icons import get_icon_bytes
from pathlib import Path
root = Path(r'$Root')
ico_path = root / 'desktop' / 'claude_master.ico'
ico_path.write_bytes(get_icon_bytes('green', 'ICO'))
png_path = root / 'desktop' / 'claude_master.png'
png_path.write_bytes(get_icon_bytes('green', 'PNG'))
print('Saved:', ico_path, 'and', png_path)
"
Write-Host "[OK] Application icons generated." -ForegroundColor Green

# 5. Create portable launchers
$cmdLauncher = Join-Path $Root "cm-desktop.cmd"
$cmdContent = @"
@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%~dp0;%PYTHONPATH%
start "" "%~dp0.venv\Scripts\pythonw.exe" -m desktop.tray 2>nul || start "" pythonw.exe -m desktop.tray 2>nul || start "" python.exe -m desktop.tray
"@
Set-Content -Path $cmdLauncher -Value $cmdContent -Encoding ASCII
Write-Host "[OK] Portable CMD launcher created: $cmdLauncher" -ForegroundColor Green

$vbsLauncher = Join-Path $Root "desktop\cm-desktop.vbs"
$vbsContent = @"
Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "$($Root -replace '\\', '\\')"
WshShell.Run "pythonw -m desktop.tray", 0, False
"@
Set-Content -Path $vbsLauncher -Value $vbsContent -Encoding ASCII
Write-Host "[OK] Silent VBS launcher created: $vbsLauncher" -ForegroundColor Green

# 6. Create Desktop shortcut
if (-not $SkipShortcut) {
  Write-Host "Creating Desktop shortcut..." -ForegroundColor Yellow
  & python -c "
from desktop.autostart import create_desktop_shortcut
lnk = create_desktop_shortcut()
print('Desktop shortcut created:', lnk)
"
  Write-Host "[OK] Desktop shortcut created." -ForegroundColor Green
}

# 7. Login autostart if requested
if ($InstallAutostart) {
  Write-Host "Configuring autostart at login..." -ForegroundColor Yellow
  & python -c "
from desktop.autostart import set_autostart
set_autostart(True)
print('Autostart configured in HKCU Run.')
"
  Write-Host "[OK] Autostart enabled." -ForegroundColor Green
}

Write-Host "=== Desktop Shell Build Complete ===" -ForegroundColor Cyan
Write-Host "To launch tray app: .\cm-desktop.cmd or python -m desktop.tray"
Write-Host "To open WebView2 window directly: python -m desktop.window"

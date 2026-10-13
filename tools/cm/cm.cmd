@echo off
rem cm — thin shim so `cm <subcommand>` works from cmd.exe and PowerShell.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0cm.ps1" %*
exit /b %ERRORLEVEL%

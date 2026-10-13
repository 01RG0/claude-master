@echo off
rem cm.cmd — claude-master CLI launcher for Windows Command Prompt and PowerShell.
setlocal
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    "%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%cli\cm.py" %*
) else (
    python "%SCRIPT_DIR%cli\cm.py" %*
)
exit /b %ERRORLEVEL%

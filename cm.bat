@echo off
rem cm.bat — claude-master CLI launcher batch file.
setlocal
set "SCRIPT_DIR=%~dp0"
if exist "%SCRIPT_DIR%.venv\Scripts\python.exe" (
    "%SCRIPT_DIR%.venv\Scripts\python.exe" "%SCRIPT_DIR%cli\cm.py" %*
) else (
    python "%SCRIPT_DIR%cli\cm.py" %*
)
exit /b %ERRORLEVEL%

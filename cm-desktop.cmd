@echo off
setlocal
cd /d "%~dp0"
set PYTHONPATH=%~dp0;%PYTHONPATH%
start "" "%~dp0.venv\Scripts\pythonw.exe" -m desktop.tray 2>nul || start "" pythonw.exe -m desktop.tray 2>nul || start "" python.exe -m desktop.tray

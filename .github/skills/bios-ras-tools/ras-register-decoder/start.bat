@echo off
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "APP_ROOT=%ROOT%\app"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%APP_ROOT%\server.ps1" -Root "%APP_ROOT%" -Port 18080

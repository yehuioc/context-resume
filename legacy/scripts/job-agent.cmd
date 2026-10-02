@echo off
setlocal
set "PYTHONUTF8=1"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0job-agent.ps1" %*
exit /b %ERRORLEVEL%

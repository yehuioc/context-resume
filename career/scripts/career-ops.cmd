@echo off
setlocal
set PYTHONUTF8=1
cd /d "%~dp0.."
python -m career_ops %*
exit /b %errorlevel%

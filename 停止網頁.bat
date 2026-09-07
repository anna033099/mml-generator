@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem Kill only the process listening on the web port, not every python.exe.
rem See msg.py for why this file stays pure ASCII.
set "PY=%USERPROFILE%\anaconda3\envs\ai24\python.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\miniconda3\envs\ai24\python.exe"
if not exist "%PY%" set "PY=python"
set "PORT=8765"
set "FOUND="
for /f "tokens=5" %%a in ('netstat -ano -p TCP ^| findstr ":%PORT% " ^| findstr "LISTENING"') do (
  set "FOUND=1"
  taskkill /F /PID %%a >nul 2>&1
)
if defined FOUND ("%PY%" msg.py stopped) else ("%PY%" msg.py not_running)
pause

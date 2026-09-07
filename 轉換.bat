@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem use the ai24 conda env if present, otherwise fall back to PATH python
set "PY=%USERPROFILE%\anaconda3\envs\ai24\python.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\miniconda3\envs\ai24\python.exe"
if not exist "%PY%" set "PY=python"
if "%~1"=="" (
  "%PY%" msg.py drag
  pause
  exit /b
)
"%PY%" mabi3.py "%~1"
echo.
"%PY%" msg.py done
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem use the ai24 conda env if present, otherwise fall back to PATH python
set "PY=%USERPROFILE%\anaconda3\envs\ai24\python.exe"
if not exist "%PY%" set "PY=%USERPROFILE%\miniconda3\envs\ai24\python.exe"
if not exist "%PY%" set "PY=python"
echo [1/2]
"%PY%" msg.py installing
"%PY%" -m pip install -r requirements.txt
echo.
echo [2/2]
"%PY%" msg.py installing_bp
"%PY%" -m pip install --no-deps basic-pitch pretty_midi mir_eval
echo.
"%PY%" msg.py installed
pause

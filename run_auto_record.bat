@echo off
title Engine Sim Automated Recorder
cd /d "%~dp0"
echo ===================================================
echo     Engine Simulator Automated Audio Recorder
echo ===================================================
echo.
echo Choose mode:
echo   1. Run instructions from 'instructions.txt'
echo   2. Run instructions from 'instructions.json'
echo   3. Interactive command line (type instructions)
echo   4. Launch UI Recorder with Auto-Batch
echo.
set /p choice="Enter choice (1-4) [default 1]: "
if "%choice%"=="" set choice=1
if "%choice%"=="1" python auto_record.py --file instructions.txt
if "%choice%"=="2" python auto_record.py --file instructions.json
if "%choice%"=="3" python auto_record.py
if "%choice%"=="4" python recorder_ui.py
pause

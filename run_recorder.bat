@echo off
title Engine Simulator - Automated Audio Recorder
cd /d "%~dp0"
echo Starting Engine Simulator Audio Recorder UI...
python engine_recorder_gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo An error occurred while running the application.
    pause
)

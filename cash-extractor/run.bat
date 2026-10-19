@echo off
chcp 65001 > nul
title Cash Income and Deposit Extractor

cd /d "%~dp0"

set PYTHONPATH=
set PYTHONHOME=

echo ============================================================
echo   Starting Cash Extractor...
echo ============================================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH!
    pause
    exit /b 1
)

python cash_extractor.py

if %errorlevel% equ 0 (
    echo.
    echo ============================================================
    echo   Process Finished Successfully!
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo   An error occurred while running the script.
    echo ============================================================
)

echo.
pause

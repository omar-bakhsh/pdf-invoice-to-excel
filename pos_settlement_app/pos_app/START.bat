@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONHOME="
set "PYTHONPATH="
set "ROOT=%~dp0"
if exist "%ROOT%.venv\Scripts\python.exe" (
 set "PY=%ROOT%.venv\Scripts\python.exe"
) else if exist "%ROOT%..\.venv\Scripts\python.exe" (
 set "PY=%ROOT%..\.venv\Scripts\python.exe"
) else (
 echo ERROR: Python environment not found.
 echo Put this BAT in pos_settlement_app or pos_app.
 pause
 exit /b 1
)
if exist "%ROOT%pos_app\app.py" (
 set "APP=%ROOT%pos_app\app.py"
) else if exist "%ROOT%app.py" (
 set "APP=%ROOT%app.py"
) else (
 echo ERROR: app.py not found.
 pause
 exit /b 1
)
echo Python: "%PY%"
echo Application: "%APP%"
"%PY%" -m pip --version >nul 2>&1
if errorlevel 1 (
 echo ERROR: pip is unavailable in this environment.
 pause
 exit /b 1
)
"%PY%" -c "import streamlit, pandas, openpyxl" >nul 2>&1
if errorlevel 1 (
 echo Installing required packages...
 "%PY%" -m pip install streamlit pandas openpyxl
 if errorlevel 1 (
  echo ERROR: Package installation failed.
  pause
  exit /b 1
 )
)
echo Starting POS settlement app...
"%PY%" -m streamlit run "%APP%"
if errorlevel 1 (
 echo Application stopped with an error.
 pause
)
endlocal

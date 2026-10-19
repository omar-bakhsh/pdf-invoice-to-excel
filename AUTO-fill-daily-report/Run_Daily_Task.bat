@echo off
TITLE Alhatem Daily Invoice Processor
:: تنظيف الإعدادات لتجنب التعارض مع BioTime
SET PYTHONPATH=
SET PYTHONHOME=

echo [1/3] Searching for new invoices in Scans folder...
"C:\Program Files\Python313\python.exe" fill_report.py

echo.
echo [DONE] Task finished successfully.
pause

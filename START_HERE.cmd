@echo off
setlocal
cd /d "%~dp0"
python "%~dp0start_here.py" --action menu
if %errorlevel% equ 9009 py -3 "%~dp0start_here.py" --action menu
if errorlevel 1 pause

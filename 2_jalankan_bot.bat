@echo off
title Eksekutor FASIH ^& Bot Nerwana
cd /d "%~dp0"

echo =================================================================
echo Memeriksa instalasi Python...
echo =================================================================

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python tidak terdeteksi di sistem PATH!
    echo Silakan install Python dan pastikan centang opsi 'Add python.exe to PATH'.
    echo.
    pause
    exit /b
)

python bersihkan_cache.py 2>nul
echo Menjalankan bot (eksekutor_fasih.py)...
echo =================================================================
python eksekutor_fasih.py

echo.
echo =================================================================
echo Proses telah selesai atau dihentikan.
echo =================================================================
pause

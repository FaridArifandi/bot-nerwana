@echo off
title Membuka Google Chrome Remote Debugging
python "%~dp0bersihkan_cache.py" 2>nul
echo =================================================================
echo Membuka Google Chrome dengan Remote Debugging Port 9222...
echo =================================================================

set CHROME_PATH=""

if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH="C:\Program Files\Google\Chrome\Application\chrome.exe"
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH="C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
) else if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" (
    set CHROME_PATH="%LocalAppData%\Google\Chrome\Application\chrome.exe"
)

if %CHROME_PATH%=="" (
    echo [ERROR] Google Chrome tidak ditemukan di folder standar!
    echo Silakan pastikan Google Chrome sudah terpasang.
    pause
    exit /b
)

echo Menjalankan Chrome dari: %CHROME_PATH%
start "" %CHROME_PATH% --remote-debugging-port=9222 --user-data-dir="%~dp0chrome_debug_profile" --start-maximized
echo Selesai. Jangan tutup jendela browser Chrome yang baru terbuka!

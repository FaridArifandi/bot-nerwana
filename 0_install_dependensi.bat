@echo off
title Setup Dependensi Bot Nerwana & Playwright
cd /d "%~dp0"

echo =================================================================
echo           SETUP OTOMATIS: DEPENDENSI & PLAYWRIGHT
echo =================================================================

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python tidak terdeteksi di sistem PATH!
    echo Silakan install Python terlebih dahulu dari https://www.python.org/downloads/
    echo dan pastikan centang opsi: 'Add python.exe to PATH'.
    echo.
    pause
    exit /b
)

echo [1/3] Menginstall library Python dari requirements.txt...
echo -----------------------------------------------------------------
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    echo [ERROR] Gagal menginstall dependensi requirements.txt!
    pause
    exit /b
)

echo.
echo [2/3] Mengunduh mesin browser Playwright Chromium...
echo -----------------------------------------------------------------
echo Menjalankan: python -m playwright install chromium
python -m playwright install chromium
if %errorlevel% neq 0 (
    echo [ERROR] Gagal menginstall browser Playwright!
    pause
    exit /b
)

echo.
echo [3/3] Memeriksa file konfigurasi akun SSO...
echo -----------------------------------------------------------------
if not exist sso (
    if exist sso.example (
        copy sso.example sso >nul
        echo File 'sso' berhasil dibuat dari sso.example.
        echo Membuka file 'sso' dengan Notepad...
        echo Harap ganti username dan password dengan akun SSO BPS Anda, lalu simpan (Ctrl+S).
        start notepad sso
    )
) else (
    echo File konfigurasi 'sso' sudah ditemukan.
)

echo.
echo =================================================================
echo               SELURUH INSTALASI BERHASIL!
echo =================================================================
echo Langkah berikutnya:
echo  1. Klik ganda '1_buka_chrome_debug.bat' (buka Selancar Nerwana)
echo  2. Klik ganda '2_jalankan_bot.bat' untuk mengeksekusi bot.
echo =================================================================
pause

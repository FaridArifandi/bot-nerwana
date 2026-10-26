@echo off
title Bersihkan Cache Bot Nerwana
cd /d "%~dp0"
echo =================================================================
echo Membersihkan cache lokal (database, riwayat, screenshot, sesi Chrome)
echo Tutup semua jendela Chrome debug dulu sebelum lanjut.
echo File 'sso' TIDAK dihapus.
echo =================================================================
pause
python bersihkan_cache.py --paksa
echo.
pause

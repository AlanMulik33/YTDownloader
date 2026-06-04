@echo off
title YT Downloader Server
color 0A

echo ==========================================
echo    YT DOWNLOADER SERVER
echo ==========================================
echo.

REM Cek apakah python tersedia
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python tidak ditemukan!
    echo Pastikan Python sudah terinstall dan ada di PATH.
    echo.
    pause
    exit /b 1
)

echo [OK] Python ditemukan.
python --version
echo.

REM Cek apakah yt-dlp terinstall
python -c "import yt_dlp" >nul 2>&1
if errorlevel 1 (
    echo [INFO] yt-dlp belum terinstall. Menginstall...
    pip install yt-dlp flask flask-cors
    echo.
)

REM Cek ffmpeg
ffmpeg -version >nul 2>&1
if errorlevel 1 (
    echo [WARNING] ffmpeg tidak ditemukan di PATH.
    echo Resolusi tinggi mungkin tidak tersedia.
    echo.
) else (
    echo [OK] ffmpeg ditemukan.
    echo.
)

echo [START] Menjalankan server...
echo Buka browser ke http://localhost:5000
echo Tekan CTRL+C untuk berhenti.
echo ==========================================
echo.

python app.py

echo.
echo Server berhenti.
pause